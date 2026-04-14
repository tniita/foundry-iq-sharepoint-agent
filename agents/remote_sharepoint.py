"""SharePoint file search agent using Foundry IQ with Remote SharePoint pattern.

This pattern uses Azure AI Search Knowledge Bases configured with a
"remoteSharePoint" knowledge source. Unlike the indexed pattern, the
SharePoint content is NOT pre-indexed into Azure AI Search. Instead,
Foundry IQ queries SharePoint directly at retrieval time via the
Microsoft Graph API, using the caller's credentials.

Architecture:
  Agent Framework (AzureAISearchContextProvider, mode="agentic")
      ↓
  Knowledge Base with remoteSharePoint source
      ↓
  Foundry IQ → Microsoft Graph API → SharePoint Online (real-time)

OBO Flow:
  User Token → OnBehalfOfCredential → Knowledge Base retrieval with user context
  The user's identity is passed through to SharePoint, ensuring access
  control (ACL) is respected at the document level.
"""

from __future__ import annotations

import asyncio
import logging
import os

from agent_framework import Agent
from agent_framework.azure import AzureAIAgentClient
from azure.identity.aio import DefaultAzureCredential, OnBehalfOfCredential
from dotenv import load_dotenv

from providers.sharepoint_context_provider import SharePointSearchContextProvider

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Remote SharePoint pattern:
#   SharePoint content is queried in real-time through the Knowledge Base.
#   No pre-indexing is required. The Knowledge Base is configured with a
#   "remoteSharePoint" knowledge source that connects to SharePoint
#   via Microsoft Graph at query time.
#
#   Key advantages:
#   - No indexer lag; always queries the latest content
#   - ACL-aware: user's permissions are enforced at query time
#   - Simpler setup (no indexer pipeline required)
#
#   Key considerations:
#   - Slightly slower due to real-time SharePoint queries
#   - Requires user-delegated credentials (OBO) for ACL enforcement
# ──────────────────────────────────────────────────────────────────────


def _build_obo_credential(
    user_assertion: str,
) -> OnBehalfOfCredential:
    """Create an OnBehalfOfCredential for OBO-based access.

    For the remote SharePoint pattern, OBO credentials are critical because
    the Knowledge Base forwards the user's identity to SharePoint via
    Microsoft Graph, ensuring document-level ACL is enforced.
    """
    return OnBehalfOfCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        user_assertion=user_assertion,
    )


async def run_remote_sharepoint_agent(
    query: str,
    user_assertion: str | None = None,
) -> None:
    """Run the SharePoint search agent using the Remote SharePoint pattern.

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
    remote_knowledge_source_name = os.environ.get("AZURE_SEARCH_REMOTE_KNOWLEDGE_SOURCE_NAME")
    remote_filter_expression_add_on = os.environ.get(
        "SHAREPOINT_REMOTE_FILTER_EXPRESSION_ADD_ON"
    )

    # For remote SharePoint, OBO credential is strongly recommended
    # to ensure user-level ACL enforcement
    if user_assertion:
        credential = _build_obo_credential(user_assertion)
        logger.info("Using OBO credential for remote SharePoint search (ACL-aware)")
    elif search_key:
        credential = None
        logger.info(
            "Using API key for remote SharePoint search "
            "(WARNING: ACL not enforced with service credentials)"
        )
    else:
        credential = DefaultAzureCredential()
        logger.info(
            "Using DefaultAzureCredential for remote SharePoint search "
            "(WARNING: ACL enforcement depends on the identity used)"
        )

    # Create Foundry IQ context provider with agentic mode
    # The Knowledge Base has a "remoteSharePoint" knowledge source configured
    search_provider = SharePointSearchContextProvider(
        source_id="sharepoint_remote_provider",
        endpoint=search_endpoint,
        api_key=search_key if not credential else None,
        credential=credential,
        mode="agentic",
        knowledge_base_name=knowledge_base_name,
        query_source_authorization=user_assertion,
        remote_knowledge_source_name=remote_knowledge_source_name,
        remote_filter_expression_add_on=remote_filter_expression_add_on,
        # extractive_data returns raw document chunks; answer_synthesis returns
        # a summarized answer from the knowledge base
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
            name="SharePointRemoteSearchAgent",
            instructions=(
                "あなたはSharePoint内のドキュメントをリアルタイム検索するアシスタントです。\n"
                "Knowledge Base（Foundry IQ）を通じてSharePointに直接アクセスし、\n"
                "最新のドキュメント内容から正確に回答してください。\n"
                "リモートSharePoint検索では、ユーザーのアクセス権限が反映されます。\n"
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
    """Entry point for the remote SharePoint search agent demo."""
    queries = [
        "SharePoint内の最新の会議議事録を検索してください",
        "プロジェクトの予算に関するファイルを探してください",
        "社内研修資料の一覧を教えてください",
    ]

    user_assertion = os.environ.get("USER_ACCESS_TOKEN")

    for q in queries:
        await run_remote_sharepoint_agent(q, user_assertion=user_assertion)


if __name__ == "__main__":
    asyncio.run(main())
