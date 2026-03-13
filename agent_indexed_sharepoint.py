"""SharePoint file search agent using Foundry IQ with Indexed SharePoint pattern.

This pattern uses Azure AI Search with a Knowledge Base configured to index
SharePoint content. The SharePoint data is pre-indexed into Azure AI Search,
enabling fast agentic retrieval via Foundry IQ (Knowledge Bases).

Architecture:
  SharePoint Site → SharePoint Indexer → Azure AI Search Index → Knowledge Base
      ↓
  Agent Framework (AzureAISearchContextProvider, mode="agentic")
      ↓
  Foundry IQ performs multi-hop reasoning over indexed SharePoint content

OBO Flow:
  User Token → OBO Exchange → Graph/SharePoint Token → Credential for Search
"""

from __future__ import annotations

import asyncio
import logging
import os

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient, AzureAISearchContextProvider
from azure.identity.aio import (
    ClientSecretCredential,
    DefaultAzureCredential,
    OnBehalfOfCredential,
)
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Indexed SharePoint pattern:
#   SharePoint content is pre-crawled by a SharePoint indexer and stored
#   in an Azure AI Search index. A Knowledge Base is then created on top
#   of that index, enabling Foundry IQ's agentic retrieval.
# ──────────────────────────────────────────────────────────────────────


def _build_obo_credential(
    user_assertion: str,
) -> OnBehalfOfCredential:
    """Create an OnBehalfOfCredential for OBO-based access to Azure AI Search.

    This allows the agent to query the search index using the caller's
    identity, ensuring row-level security and access controls are respected.
    """
    return OnBehalfOfCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        user_assertion=user_assertion,
    )


async def run_indexed_sharepoint_agent(
    query: str,
    user_assertion: str | None = None,
) -> None:
    """Run the SharePoint search agent using the Indexed SharePoint pattern.

    Args:
        query: The user's search query.
        user_assertion: Optional user Bearer token for OBO flow.
                        If None, DefaultAzureCredential is used.
    """
    search_endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    search_key = os.environ.get("AZURE_SEARCH_API_KEY")
    project_endpoint = os.environ["AZURE_AI_PROJECT_ENDPOINT"]
    model_deployment = os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "gpt-4o")
    knowledge_base_name = os.environ["AZURE_SEARCH_KNOWLEDGE_BASE_NAME"]

    # Determine credential: OBO flow or default
    if user_assertion:
        credential = _build_obo_credential(user_assertion)
        logger.info("Using OBO credential for indexed SharePoint search")
    elif search_key:
        credential = None
        logger.info("Using API key for indexed SharePoint search")
    else:
        credential = DefaultAzureCredential()
        logger.info("Using DefaultAzureCredential for indexed SharePoint search")

    # Create Foundry IQ context provider with agentic mode
    # The Knowledge Base is pre-configured with an "indexedSharePoint" source
    search_provider = AzureAISearchContextProvider(
        source_id="sharepoint_indexed_provider",
        endpoint=search_endpoint,
        api_key=search_key if not credential else None,
        credential=credential,
        mode="agentic",
        knowledge_base_name=knowledge_base_name,
        knowledge_base_output_mode="extractive_data",
        retrieval_reasoning_effort="medium",
    )

    async with (
        search_provider,
        AzureAIAgentClient(
            project_endpoint=project_endpoint,
            model_deployment_name=model_deployment,
            credential=(
                _build_obo_credential(user_assertion)
                if user_assertion
                else DefaultAzureCredential()
            ),
        ) as client,
        Agent(
            client=client,
            name="SharePointIndexedSearchAgent",
            instructions=(
                "あなたはSharePoint内のドキュメントを検索するアシスタントです。\n"
                "Knowledge Base（Foundry IQ）のコンテキストを使用して、\n"
                "SharePointにインデックスされたファイルから正確に回答してください。\n"
                "回答する際は、参照元のドキュメント名やURLがあれば提示してください。"
            ),
            context_providers=[search_provider],
        ) as agent,
    ):
        print(f"User: {query}")
        print("Agent: ", end="", flush=True)

        async for chunk in agent.run(query, stream=True):
            if chunk.text:
                print(chunk.text, end="", flush=True)
            for content in chunk.contents:
                if content.annotations:
                    print(f"\n[参照: {content.annotations}]", end="", flush=True)

        print("\n")


async def main() -> None:
    """Entry point for the indexed SharePoint search agent demo."""
    queries = [
        "SharePoint内の社内規定に関するドキュメントを検索してください",
        "最新のプロジェクト計画書の内容を要約してください",
        "人事関連のポリシーについて教えてください",
    ]

    # In a real application, user_assertion would come from the HTTP request
    # Authorization header forwarded through the middleware
    user_assertion = os.environ.get("USER_ACCESS_TOKEN")

    for q in queries:
        await run_indexed_sharepoint_agent(q, user_assertion=user_assertion)


if __name__ == "__main__":
    asyncio.run(main())
