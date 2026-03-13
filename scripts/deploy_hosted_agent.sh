#!/usr/bin/env bash

set -euo pipefail

require_env() {
    local name="$1"
    if [[ -z "${!name:-}" ]]; then
        echo "Missing required environment variable: ${name}" >&2
        exit 1
    fi
}

require_command() {
    local name="$1"
    if ! command -v "$name" >/dev/null 2>&1; then
        echo "Required command not found: ${name}" >&2
        exit 1
    fi
}

require_command az

PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "${PYTHON_BIN}" ]]; then
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_BIN="python"
    else
        echo "Required command not found: python3 or python" >&2
        exit 1
    fi
fi

require_env AZURE_SUBSCRIPTION_ID
require_env AZURE_RESOURCE_GROUP
require_env AZURE_FOUNDRY_ACCOUNT_NAME
require_env AZURE_FOUNDRY_PROJECT_NAME
require_env AZURE_CONTAINER_REGISTRY_NAME
require_env AZURE_AI_AGENT_NAME
require_env AZURE_AI_MODEL_DEPLOYMENT_NAME

if [[ -z "${AZURE_AI_PROJECT_ENDPOINT:-}" ]]; then
    export AZURE_AI_PROJECT_ENDPOINT="https://${AZURE_FOUNDRY_ACCOUNT_NAME}.services.ai.azure.com/api/projects/${AZURE_FOUNDRY_PROJECT_NAME}"
fi

if [[ -z "${AZURE_AI_PROJECT_RESOURCE_ID:-}" ]]; then
    export AZURE_AI_PROJECT_RESOURCE_ID="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${AZURE_FOUNDRY_ACCOUNT_NAME}/projects/${AZURE_FOUNDRY_PROJECT_NAME}"
fi

: "${SHAREPOINT_SEARCH_PATTERN:=indexed}"
: "${AZURE_ACR_REPOSITORY:=${AZURE_AI_AGENT_NAME}}"
: "${HOSTED_AGENT_CPU:=1}"
: "${HOSTED_AGENT_MEMORY:=2Gi}"
: "${HOSTED_AGENT_MIN_REPLICAS:=0}"
: "${HOSTED_AGENT_MAX_REPLICAS:=1}"
: "${AZURE_IMAGE_TAG:=$(date -u +%Y%m%d%H%M%S)}"

echo "Resolving Azure resource identifiers..."
ACCOUNT_RESOURCE_ID="/subscriptions/${AZURE_SUBSCRIPTION_ID}/resourceGroups/${AZURE_RESOURCE_GROUP}/providers/Microsoft.CognitiveServices/accounts/${AZURE_FOUNDRY_ACCOUNT_NAME}"
ACR_ID="$(az acr show --name "${AZURE_CONTAINER_REGISTRY_NAME}" --subscription "${AZURE_SUBSCRIPTION_ID}" --query id -o tsv)"
ACR_LOGIN_SERVER="$(az acr show --name "${AZURE_CONTAINER_REGISTRY_NAME}" --subscription "${AZURE_SUBSCRIPTION_ID}" --query loginServer -o tsv)"
PROJECT_PRINCIPAL_ID="$(az resource show --ids "${AZURE_AI_PROJECT_RESOURCE_ID}" --api-version 2025-10-01-preview --query identity.principalId -o tsv)"

export HOSTED_AGENT_IMAGE="${ACR_LOGIN_SERVER}/${AZURE_ACR_REPOSITORY}:${AZURE_IMAGE_TAG}"

echo "Building container image ${HOSTED_AGENT_IMAGE} in ACR..."
az acr build \
    --registry "${AZURE_CONTAINER_REGISTRY_NAME}" \
    --image "${AZURE_ACR_REPOSITORY}:${AZURE_IMAGE_TAG}" \
    --platform linux/amd64 \
    .

echo "Ensuring Foundry capability host exists..."
az rest \
    --method put \
    --url "https://management.azure.com${ACCOUNT_RESOURCE_ID}/capabilityHosts/accountcaphost?api-version=2025-10-01-preview" \
    --headers content-type=application/json \
    --body '{"properties":{"capabilityHostKind":"Agents","enablePublicHostingEnvironment":true}}' \
    >/dev/null

if [[ -n "${PROJECT_PRINCIPAL_ID}" ]]; then
    echo "Granting AcrPull to project managed identity..."
    az role assignment create \
        --assignee-object-id "${PROJECT_PRINCIPAL_ID}" \
        --assignee-principal-type ServicePrincipal \
        --role AcrPull \
        --scope "${ACR_ID}" \
        >/dev/null || true
fi

echo "Creating hosted agent version..."
AGENT_VERSION="$(${PYTHON_BIN} scripts/create_hosted_agent_version.py)"

echo "Starting hosted agent deployment..."
az cognitiveservices agent start \
    --subscription "${AZURE_SUBSCRIPTION_ID}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --account-name "${AZURE_FOUNDRY_ACCOUNT_NAME}" \
    --project-name "${AZURE_FOUNDRY_PROJECT_NAME}" \
    --name "${AZURE_AI_AGENT_NAME}" \
    --agent-version "${AGENT_VERSION}" \
    --min-replicas "${HOSTED_AGENT_MIN_REPLICAS}" \
    --max-replicas "${HOSTED_AGENT_MAX_REPLICAS}"

echo
echo "Hosted agent deployment started."
echo "  Agent name: ${AZURE_AI_AGENT_NAME}"
echo "  Agent version: ${AGENT_VERSION}"
echo "  Project endpoint: ${AZURE_AI_PROJECT_ENDPOINT}"
echo "  Image: ${HOSTED_AGENT_IMAGE}"