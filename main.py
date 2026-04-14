"""Hosted Agent entry point for Microsoft Foundry.

Runs the SharePoint search agent behind the Azure AI AgentServer adapter so the
container exposes an OpenAI Responses-compatible endpoint on port 8088.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Literal

from agent_framework.azure import AzureAIAgentClient
from azure.ai.agentserver.agentframework import from_agent_framework
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from agents.sharepoint_agent import SharePointSearchAgent

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _resolve_pattern() -> Literal["indexed", "remote"]:
    pattern = os.environ.get("SHAREPOINT_SEARCH_PATTERN", "indexed").strip().lower()
    if pattern not in {"indexed", "remote"}:
        raise ValueError(
            "SHAREPOINT_SEARCH_PATTERN must be either 'indexed' or 'remote'."
        )
    return pattern  # type: ignore[return-value]


async def run_hosted_agent() -> None:
    """Run the agent as a Microsoft Foundry Hosted Agent."""
    pattern = _resolve_pattern()
    backend = SharePointSearchAgent(pattern=pattern)
    search_provider = backend.create_search_provider()

    async with (
        DefaultAzureCredential() as credential,
        search_provider,
        AzureAIAgentClient(
            project_endpoint=backend.project_endpoint,
            model_deployment_name=backend.model_deployment,
            credential=credential,
        ) as client,
        backend.create_agent(client, search_provider) as agent,
    ):
        logger.info("Starting SharePoint hosted agent with pattern=%s", pattern)
        await from_agent_framework(agent).run_async()


if __name__ == "__main__":
    asyncio.run(run_hosted_agent())