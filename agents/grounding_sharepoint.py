"""SharePoint search agent using Azure AI Project Agent Provider.

This is an alternative approach that uses the Foundry Agent's built-in
SharePoint grounding tool (sharepoint_grounding_preview) instead of
Foundry IQ Knowledge Bases. This pattern is simpler to set up but
provides less control over retrieval behavior.

Prerequisites:
  - Azure AI Foundry project with a SharePoint connection configured
  - SHAREPOINT_PROJECT_CONNECTION_ID environment variable set
"""

from __future__ import annotations

import asyncio
import logging
import os

from agent_framework.azure import AzureAIProjectAgentProvider
from azure.identity.aio import DefaultAzureCredential, OnBehalfOfCredential
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _build_obo_credential(user_assertion: str) -> OnBehalfOfCredential:
    """Create OBO credential for delegated SharePoint access."""
    return OnBehalfOfCredential(
        tenant_id=os.environ["AZURE_TENANT_ID"],
        client_id=os.environ["AZURE_CLIENT_ID"],
        client_secret=os.environ["AZURE_CLIENT_SECRET"],
        user_assertion=user_assertion,
    )


async def run_sharepoint_grounding_agent(
    query: str,
    user_assertion: str | None = None,
) -> None:
    """Run the SharePoint search agent using Foundry's SharePoint grounding tool.

    This pattern uses the Azure AI Agent Service's built-in SharePoint
    grounding capability, which provides direct access to SharePoint
    content through a project connection.

    Args:
        query: The user's search query.
        user_assertion: Optional user Bearer token for OBO flow.
    """
    sharepoint_connection_id = os.environ["SHAREPOINT_PROJECT_CONNECTION_ID"]

    # Determine credential
    if user_assertion:
        credential = _build_obo_credential(user_assertion)
        logger.info("Using OBO credential for SharePoint grounding")
    else:
        credential = DefaultAzureCredential()
        logger.info("Using DefaultAzureCredential for SharePoint grounding")

    async with (
        credential,
        AzureAIProjectAgentProvider(credential=credential) as provider,
    ):
        agent = await provider.create_agent(
            name="SharePointGroundingAgent",
            instructions=(
                "あなたはSharePoint内のドキュメントを検索するアシスタントです。\n"
                "SharePointツールを使用して、ユーザーの質問に関連する\n"
                "ドキュメントを検索し、正確に回答してください。\n"
                "回答する際は、参照元のドキュメント名やURLがあれば提示してください。"
            ),
            tools={
                "type": "sharepoint_grounding_preview",
                "sharepoint_grounding_preview": {
                    "project_connections": [
                        {
                            "project_connection_id": sharepoint_connection_id,
                        }
                    ]
                },
            },
        )

        print(f"User: {query}")
        result = await agent.run(query)
        print(f"Agent: {result}\n")


async def main() -> None:
    """Entry point for the SharePoint grounding agent demo."""
    queries = [
        "社内規定に関するドキュメントを検索してください",
        "最新のプロジェクト計画書の内容を要約してください",
    ]

    user_assertion = os.environ.get("USER_ACCESS_TOKEN")

    for q in queries:
        await run_sharepoint_grounding_agent(q, user_assertion=user_assertion)


if __name__ == "__main__":
    asyncio.run(main())
