"""Provider abstraction for BYOK LLM backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel


@dataclass
class ValidationOutcome:
    valid: bool
    message: str


class BaseLLMProvider(ABC):
    name: str = "base"
    default_model: str = ""

    @abstractmethod
    async def validate(self, api_key: str, config: dict[str, Any]) -> ValidationOutcome: ...

    @abstractmethod
    async def list_models(self, api_key: str, config: dict[str, Any]) -> list[dict[str, str]]: ...

    @abstractmethod
    def chat_model(
        self, api_key: str, config: dict[str, Any], model: str | None, temperature: float
    ) -> BaseChatModel: ...

    @abstractmethod
    def embeddings(self, api_key: str, config: dict[str, Any]) -> Embeddings: ...
