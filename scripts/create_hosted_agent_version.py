"""Create a Microsoft Foundry hosted agent version for this project."""

from __future__ import annotations

import os
import sys

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import AgentProtocol, HostedAgentDefinition, ProtocolVersionRecord
from azure.identity import DefaultAzureCredential


def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required.")
    return value


def _build_runtime_environment() -> dict[str, str]:
    runtime_vars = [
        "AZURE_AI_PROJECT_ENDPOINT",
        "AZURE_AI_MODEL_DEPLOYMENT_NAME",
        "AZURE_SEARCH_ENDPOINT",
        "AZURE_SEARCH_API_KEY",
        "AZURE_SEARCH_KNOWLEDGE_BASE_NAME",
        "SHAREPOINT_SEARCH_PATTERN",
        "OTEL_EXPORTER_ENDPOINT",
    ]
    return {
        name: value
        for name in runtime_vars
        if (value := os.environ.get(name, "").strip())
    }


def main() -> int:
    project_endpoint = _require_env("AZURE_AI_PROJECT_ENDPOINT")
    agent_name = _require_env("AZURE_AI_AGENT_NAME")
    image = _require_env("HOSTED_AGENT_IMAGE")
    cpu = os.environ.get("HOSTED_AGENT_CPU", "1").strip() or "1"
    memory = os.environ.get("HOSTED_AGENT_MEMORY", "2Gi").strip() or "2Gi"

    project = AIProjectClient(
        endpoint=project_endpoint,
        credential=DefaultAzureCredential(),
        allow_preview=True,
    )

    definition = HostedAgentDefinition(
        image=image,
        cpu=cpu,
        memory=memory,
        container_protocol_versions=[
            ProtocolVersionRecord(protocol=AgentProtocol.RESPONSES, version="v1")
        ],
        environment_variables=_build_runtime_environment(),
    )

    agent = project.agents.create_version(
        agent_name=agent_name,
        definition=definition,
    )
    print(agent.version)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Failed to create hosted agent version: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc