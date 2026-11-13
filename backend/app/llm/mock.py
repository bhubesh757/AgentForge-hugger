"""Deterministic mock provider (LLM_MOCK_MODE=true and api key starting with 'mock-')."""

from __future__ import annotations

from typing import Any

from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core.config import settings
from app.llm.base import BaseLLMProvider, ValidationOutcome

MOCK_RESPONSE = "This is a deterministic mock response from AgentForge."


def is_mock_key(api_key: str) -> bool:
    return settings.LLM_MOCK_MODE and api_key.startswith("mock-")


class MockProvider(BaseLLMProvider):
    name = "mock"
    default_model = "mock-model"

    async def validate(self, api_key: str, config: dict[str, Any]) -> ValidationOutcome:
        return ValidationOutcome(True, "Mock key accepted (LLM_MOCK_MODE)")

    async def list_models(self, api_key: str, config: dict[str, Any]) -> list[dict[str, str]]:
        return [{"id": "mock-model", "display_name": "Mock Model"}]

    def chat_model(self, api_key, config, model, temperature):
        return FakeListChatModel(responses=[MOCK_RESPONSE])

    def embeddings(self, api_key, config):
        return DeterministicFakeEmbedding(size=settings.EMBEDDING_DIM)
