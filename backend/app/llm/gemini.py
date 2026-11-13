from __future__ import annotations

from typing import Any

import httpx

from app.llm.base import BaseLLMProvider, ValidationOutcome

_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(BaseLLMProvider):
    name = "gemini"
    default_model = "gemini-2.0-flash"

    async def _get_models(self, api_key: str) -> httpx.Response:
        async with httpx.AsyncClient(timeout=10) as c:
            return await c.get(f"{_BASE}/models", headers={"x-goog-api-key": api_key})

    async def validate(self, api_key: str, config: dict[str, Any]) -> ValidationOutcome:
        try:
            r = await self._get_models(api_key)
        except httpx.HTTPError as exc:
            return ValidationOutcome(False, f"Could not reach Gemini API: {type(exc).__name__}")
        if r.status_code == 200:
            return ValidationOutcome(True, "Gemini API key is valid")
        return ValidationOutcome(False, f"Gemini rejected the key (HTTP {r.status_code})")

    async def list_models(self, api_key: str, config: dict[str, Any]) -> list[dict[str, str]]:
        r = await self._get_models(api_key)
        r.raise_for_status()
        out = []
        for m in r.json().get("models", []):
            if "generateContent" in m.get("supportedGenerationMethods", []):
                mid = m["name"].removeprefix("models/")
                out.append({"id": mid, "display_name": m.get("displayName", mid)})
        return out

    def chat_model(self, api_key, config, model, temperature):
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model or self.default_model, google_api_key=api_key, temperature=temperature
        )

    def embeddings(self, api_key, config):
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(model="models/text-embedding-004", google_api_key=api_key)
