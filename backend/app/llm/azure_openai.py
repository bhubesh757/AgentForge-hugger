from __future__ import annotations

from typing import Any

import httpx

from app.llm.base import BaseLLMProvider, ValidationOutcome


class AzureOpenAIProvider(BaseLLMProvider):
    name = "azure_openai"
    default_model = ""

    @staticmethod
    def _url(config: dict[str, Any], path: str) -> str:
        return f"{config['endpoint'].rstrip('/')}/openai/{path}?api-version={config['api_version']}"

    async def validate(self, api_key: str, config: dict[str, Any]) -> ValidationOutcome:
        url = self._url(config, f"deployments/{config['deployment_name']}/chat/completions")
        body = {"messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.post(url, headers={"api-key": api_key}, json=body)
        except httpx.HTTPError as exc:
            return ValidationOutcome(False, f"Could not reach Azure OpenAI endpoint: {type(exc).__name__}")
        if r.status_code == 200:
            return ValidationOutcome(True, "Azure OpenAI deployment reachable")
        return ValidationOutcome(False, f"Azure OpenAI rejected the request (HTTP {r.status_code})")

    async def list_models(self, api_key: str, config: dict[str, Any]) -> list[dict[str, str]]:
        dep = config.get("deployment_name", "")
        return [{"id": dep, "display_name": f"{dep} (deployment)"}] if dep else []

    def chat_model(self, api_key, config, model, temperature):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=config["endpoint"],
            api_key=api_key,
            azure_deployment=model or config["deployment_name"],
            api_version=config["api_version"],
            temperature=temperature,
        )

    def embeddings(self, api_key, config):
        from langchain_openai import AzureOpenAIEmbeddings

        return AzureOpenAIEmbeddings(
            azure_endpoint=config["endpoint"],
            api_key=api_key,
            azure_deployment=config.get("embedding_deployment", "text-embedding-3-small"),
            api_version=config["api_version"],
        )
