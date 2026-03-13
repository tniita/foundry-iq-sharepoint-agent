from __future__ import annotations

import logging
from typing import Literal

from agent_framework import Message
from agent_framework.azure import AzureAISearchContextProvider
from azure.search.documents.knowledgebases.models import (
    KnowledgeBaseRetrievalRequest,
    KnowledgeRetrievalIntent,
    KnowledgeRetrievalLowReasoningEffort,
    KnowledgeRetrievalMediumReasoningEffort,
    KnowledgeRetrievalMinimalReasoningEffort,
    KnowledgeRetrievalOutputMode,
    KnowledgeRetrievalReasoningEffort,
    KnowledgeRetrievalSemanticIntent,
    RemoteSharePointKnowledgeSourceParams,
)

logger = logging.getLogger(__name__)


class SharePointSearchContextProvider(AzureAISearchContextProvider):
    """Project-local extension for remote SharePoint runtime retrieval parameters."""

    def __init__(
        self,
        *args,
        query_source_authorization: str | None = None,
        remote_knowledge_source_name: str | None = None,
        remote_filter_expression_add_on: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.query_source_authorization = query_source_authorization
        self.remote_knowledge_source_name = remote_knowledge_source_name
        self.remote_filter_expression_add_on = remote_filter_expression_add_on

    @staticmethod
    def _format_query_source_authorization(token: str | None) -> str | None:
        if not token:
            return None
        normalized = token.strip()
        if not normalized:
            return None
        if normalized.lower().startswith("bearer "):
            return normalized
        return f"Bearer {normalized}"

    def _build_knowledge_source_params(self) -> list[RemoteSharePointKnowledgeSourceParams] | None:
        if not self.remote_knowledge_source_name:
            return None

        params = RemoteSharePointKnowledgeSourceParams(
            knowledge_source_name=self.remote_knowledge_source_name,
            filter_expression_add_on=self.remote_filter_expression_add_on,
        )
        return [params]

    async def _agentic_search(self, messages: list[Message]) -> list[Message]:
        await self._ensure_knowledge_base()

        reasoning_effort_map: dict[str, KnowledgeRetrievalReasoningEffort] = {
            "minimal": KnowledgeRetrievalMinimalReasoningEffort(),
            "medium": KnowledgeRetrievalMediumReasoningEffort(),
            "low": KnowledgeRetrievalLowReasoningEffort(),
        }
        reasoning_effort = reasoning_effort_map[self.retrieval_reasoning_effort]

        output_mode = (
            KnowledgeRetrievalOutputMode.EXTRACTIVE_DATA
            if self.knowledge_base_output_mode == "extractive_data"
            else KnowledgeRetrievalOutputMode.ANSWER_SYNTHESIS
        )

        if self.retrieval_reasoning_effort == "minimal":
            query = "\n".join(msg.text for msg in messages if msg.text)
            intents: list[KnowledgeRetrievalIntent] = [KnowledgeRetrievalSemanticIntent(search=query)]
            retrieval_request = KnowledgeBaseRetrievalRequest(
                intents=intents,
                retrieval_reasoning_effort=reasoning_effort,
                output_mode=output_mode,
                include_activity=True,
            )
        else:
            kb_messages = self._prepare_messages_for_kb_search(messages)
            retrieval_request = KnowledgeBaseRetrievalRequest(
                messages=kb_messages,
                retrieval_reasoning_effort=reasoning_effort,
                output_mode=output_mode,
                include_activity=True,
            )

        knowledge_source_params = self._build_knowledge_source_params()
        if knowledge_source_params:
            retrieval_request.knowledge_source_params = knowledge_source_params
            if self.remote_filter_expression_add_on:
                logger.info(
                    "Applying remote SharePoint filterExpressionAddOn to knowledge source '%s'",
                    self.remote_knowledge_source_name,
                )

        if not self._retrieval_client:
            raise RuntimeError("Retrieval client not initialized.")

        retrieval_result = await self._retrieval_client.retrieve(
            retrieval_request=retrieval_request,
            x_ms_query_source_authorization=self._format_query_source_authorization(
                self.query_source_authorization
            ),
        )

        return self._parse_messages_from_kb_response(retrieval_result)