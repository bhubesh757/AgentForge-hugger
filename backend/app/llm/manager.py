"""Resolve an org's BYOK provider into LangChain models (contract section 13)."""

from __future__ import annotations

import uuid

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.credentials.cipher import get_cipher
from app.database.models import LLMProvider
from app.llm.azure_openai import AzureOpenAIProvider
from app.llm.base import BaseLLMProvider
from app.llm.gemini import GeminiProvider
from app.llm.mock import MockProvider, is_mock_key

PROVIDERS: dict[str, BaseLLMProvider] = {"gemini": GeminiProvider(), "azure_openai": AzureOpenAIProvider()}
_MOCK = MockProvider()


def provider_impl(provider: str, api_key: str) -> BaseLLMProvider:
    if is_mock_key(api_key):
        return _MOCK
    return PROVIDERS[provider]


async def resolve_provider(
    session: AsyncSession, organization_id: uuid.UUID, provider_id: uuid.UUID | None = None
) -> LLMProvider:
    stmt = select(LLMProvider).where(LLMProvider.organization_id == organization_id)
    if provider_id is not None:
        stmt = stmt.where(LLMProvider.id == provider_id)
    else:
        stmt = stmt.where(LLMProvider.is_default.is_(True), LLMProvider.status == "active")
    row = (await session.execute(stmt)).scalar_one_or_none()
    if row is None:
        raise AppError(
            422,
            "VALIDATION_ERROR",
            "No active LLM provider configured for this organization"
            if provider_id is None
            else "LLM provider not found",
        )
    if row.status not in {"valid", "active"}:
        raise AppError(422, "VALIDATION_ERROR", f"LLM provider is not usable (status {row.status})")
    return row


async def get_chat_model(
    session: AsyncSession,
    organization_id: uuid.UUID,
    provider_id: uuid.UUID | None = None,
    model: str | None = None,
    temperature: float = 0.2,
) -> BaseChatModel:
    row = await resolve_provider(session, organization_id, provider_id)
    key = get_cipher().decrypt(row.encrypted_api_key)
    impl = provider_impl(row.provider, key)
    return impl.chat_model(key, row.config or {}, model or row.default_model, temperature)


async def get_embeddings(session: AsyncSession, organization_id: uuid.UUID) -> Embeddings:
    try:
        row = await resolve_provider(session, organization_id)
    except AppError:
        if settings.LLM_MOCK_MODE:
            return _MOCK.embeddings("mock-", {})
        raise
    key = get_cipher().decrypt(row.encrypted_api_key)
    return provider_impl(row.provider, key).embeddings(key, row.config or {})
