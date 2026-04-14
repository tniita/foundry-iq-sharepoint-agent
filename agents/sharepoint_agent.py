"""SharePoint search backend for local and hosted Microsoft Foundry agents.

This module exposes a reusable search backend that can be consumed from:
- Hosted Agent runtime via Azure AI AgentServer SDK
- Legacy local scripts and HTTP wrappers
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Literal

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient, AzureAISearchContextProvider
from azure.identity.aio import DefaultAzureCredential, OnBehalfOfCredential
from dotenv import load_dotenv

from providers.sharepoint_context_provider import SharePointSearchContextProvider

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SharePointSearchAgent:
    """Foundry IQ backend for searching SharePoint documents.

    Supports two retrieval patterns:
    - "indexed": SharePoint content is pre-indexed into Azure AI Search.
      Faster queries, but content may be stale until re-indexed.
    - "remote": SharePoint content is queried in real-time via Microsoft Graph.
            Always up-to-date, but slightly slower. Per-user ACL enforcement requires
            OBO only when a delegated end-user token is available.

    Both patterns leverage Foundry IQ's agentic retrieval for multi-hop
        reasoning and intelligent query planning.

        Runtime model:
        - Hosted Agent path: create_search_provider() is called without a
            user_assertion, so the search layer uses Managed Identity or
            DefaultAzureCredential.
        - Legacy HTTP path: api_server.py extracts a Bearer token, strips the
            Authorization label, and passes the raw token as user_assertion so OBO is
            used for delegated access.
    """

    def __init__(
        self,
        pattern: Literal["indexed", "remote"] = "indexed",
        search_endpoint: str | None = None,
        search_api_key: str | None = None,
        project_endpoint: str | None = None,
        model_deployment: str | None = None,
        knowledge_base_name: str | None = None,
        tenant_id: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> None:
        self.pattern = pattern
        self.search_endpoint = search_endpoint or os.environ["AZURE_SEARCH_ENDPOINT"]
        self.search_api_key = search_api_key or os.environ.get("AZURE_SEARCH_API_KEY")
        self.project_endpoint = project_endpoint or os.environ["AZURE_AI_PROJECT_ENDPOINT"]
        self.model_deployment = model_deployment or os.environ.get(
            "AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o"
        )
        self.knowledge_base_name = knowledge_base_name or os.environ[
            "AZURE_SEARCH_KNOWLEDGE_BASE_NAME"
        ]
        self.remote_knowledge_source_name = os.environ.get(
            "AZURE_SEARCH_REMOTE_KNOWLEDGE_SOURCE_NAME"
        )
        self.remote_filter_expression_add_on = os.environ.get(
            "SHAREPOINT_REMOTE_FILTER_EXPRESSION_ADD_ON"
        )

        # OBO configuration
        self._tenant_id = tenant_id or os.environ.get("AZURE_TENANT_ID")
        self._client_id = client_id or os.environ.get("AZURE_CLIENT_ID")
        self._client_secret = client_secret or os.environ.get("AZURE_CLIENT_SECRET")

    def _get_credential(
        self,
        user_assertion: str | None = None,
    ) -> OnBehalfOfCredential | DefaultAzureCredential | None:
        """Resolve credential based on delegated-token availability.

        If user_assertion is provided, use OBO for delegated user-context
        access. Otherwise prefer API key if configured, or fall back to
        DefaultAzureCredential / Managed Identity.
        """
        if user_assertion and self._tenant_id and self._client_id and self._client_secret:
            return OnBehalfOfCredential(
                tenant_id=self._tenant_id,
                client_id=self._client_id,
                client_secret=self._client_secret,
                user_assertion=user_assertion,
            )
        if self.search_api_key:
            return None
        return DefaultAzureCredential()

    def _log_credential_mode(self, user_assertion: str | None = None) -> None:
        credential = self._get_credential(user_assertion)
        if credential is not None:
            logger.info(
                "SharePoint search [%s] using %s credential",
                self.pattern,
                "OBO" if user_assertion else "default",
            )
        else:
            logger.info("SharePoint search [%s] using API key", self.pattern)

    def _get_instructions(self) -> str:
        """Return agent instructions based on pattern type."""
        if self.pattern == "indexed":
            return (
                "あなたはSharePoint内のドキュメントを検索するアシスタントです。\n"
                "Knowledge Base（Foundry IQ）のコンテキストを使用して、\n"
                "SharePointにインデックスされたファイルから正確に回答してください。\n"
                "回答する際は、参照元のドキュメント名やURLがあれば提示してください。\n"
                "ユーザーの質問に対して、関連するドキュメントの内容を要約して回答してください。"
            )
        return (
            "あなたはSharePoint内のドキュメントをリアルタイム検索するアシスタントです。\n"
            "Knowledge Base（Foundry IQ）を通じてSharePointに直接アクセスし、\n"
            "最新のドキュメント内容から正確に回答してください。\n"
            "リモートSharePoint検索では、ユーザーのアクセス権限が反映されます。\n"
            "回答する際は、参照元のドキュメント名やURLがあれば提示してください。\n"
            "ユーザーの質問に対して、関連するドキュメントの内容を要約して回答してください。"
        )

    def create_search_provider(
        self,
        user_assertion: str | None = None,
    ) -> AzureAISearchContextProvider:
        """Create the Azure AI Search context provider for the configured pattern."""
        credential = self._get_credential(user_assertion)
        provider_kwargs: dict[str, object] = {
            "query_source_authorization": user_assertion,
        }
        if self.pattern == "remote":
            provider_kwargs["remote_knowledge_source_name"] = self.remote_knowledge_source_name
            provider_kwargs["remote_filter_expression_add_on"] = self.remote_filter_expression_add_on
        return SharePointSearchContextProvider(
            source_id=f"sharepoint_{self.pattern}_provider",
            endpoint=self.search_endpoint,
            api_key=self.search_api_key if not credential else None,
            credential=credential,
            mode="agentic",
            knowledge_base_name=self.knowledge_base_name,
            knowledge_base_output_mode="extractive_data",
            retrieval_reasoning_effort="medium",
            **provider_kwargs,
        )

    def create_agent(
        self,
        client: AzureAIAgentClient,
        search_provider: AzureAISearchContextProvider,
    ) -> Agent:
        """Create the Agent Framework agent bound to the SharePoint knowledge base."""
        return Agent(
            client=client,
            name=f"SharePoint{'Indexed' if self.pattern == 'indexed' else 'Remote'}HostedAgent",
            instructions=self._get_instructions(),
            context_providers=[search_provider],
        )

    async def search(
        self,
        query: str,
        user_assertion: str | None = None,
    ) -> str:
        """Search SharePoint documents and return the agent's response.

        Args:
            query: The user's search query.
            user_assertion: Optional raw access token string for OBO flow.
                Do not include the 'Bearer ' prefix.

        Returns:
            The agent's response text.
        """
        self._log_credential_mode(user_assertion)
        search_provider = self.create_search_provider(user_assertion)
        project_credential = self._get_credential(user_assertion) or DefaultAzureCredential()

        async with (
            search_provider,
            AzureAIAgentClient(
                project_endpoint=self.project_endpoint,
                model_deployment_name=self.model_deployment,
                credential=project_credential,
            ) as client,
            self.create_agent(client, search_provider) as agent,
        ):
            response_parts: list[str] = []
            async for chunk in agent.run(query, stream=True):
                if chunk.text:
                    response_parts.append(chunk.text)

            return "".join(response_parts)

    async def search_stream(
        self,
        query: str,
        user_assertion: str | None = None,
    ) -> AsyncIterator[str]:
        """Search SharePoint documents and yield streaming response chunks.

        Args:
            query: The user's search query.
            user_assertion: Optional raw access token string for OBO flow.
                Do not include the 'Bearer ' prefix.

        Yields:
            Response text chunks as they arrive.
        """
        self._log_credential_mode(user_assertion)
        search_provider = self.create_search_provider(user_assertion)
        project_credential = self._get_credential(user_assertion) or DefaultAzureCredential()

        async with (
            search_provider,
            AzureAIAgentClient(
                project_endpoint=self.project_endpoint,
                model_deployment_name=self.model_deployment,
                credential=project_credential,
            ) as client,
            self.create_agent(client, search_provider) as agent,
        ):
            async for chunk in agent.run(query, stream=True):
                if chunk.text:
                    yield chunk.text


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────


async def main() -> None:
    """Interactive CLI for testing both SharePoint search patterns."""
    import sys

    pattern: Literal["indexed", "remote"] = "indexed"
    if len(sys.argv) > 1 and sys.argv[1] in ("indexed", "remote"):
        pattern = sys.argv[1]  # type: ignore[assignment]

    user_assertion = os.environ.get("USER_ACCESS_TOKEN")

    agent = SharePointSearchAgent(pattern=pattern)
    print(f"=== SharePoint Search Agent ({pattern} pattern) ===")
    print("Type 'quit' to exit, 'switch' to toggle pattern\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not query:
            continue
        if query.lower() == "quit":
            break
        if query.lower() == "switch":
            pattern = "remote" if pattern == "indexed" else "indexed"
            agent = SharePointSearchAgent(pattern=pattern)
            print(f"Switched to {pattern} pattern\n")
            continue

        print("Agent: ", end="", flush=True)
        async for text in agent.search_stream(query, user_assertion=user_assertion):
            print(text, end="", flush=True)
        print("\n")


if __name__ == "__main__":
    asyncio.run(main())
