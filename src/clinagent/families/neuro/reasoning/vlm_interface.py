"""Unified interface for calling Vision-Language Models."""
from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError


class VLMInterface(ABC):
    """Abstract multimodal generation interface."""

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> str:
        """Generate text from a text/image message bundle."""


class OpenAIVLM(VLMInterface):
    """OpenAI Responses API implementation for multimodal neuro prompts."""

    def __init__(
        self,
        model: str = "gpt-4o",
        api_key: str | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.model = model
        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        if client is None and not resolved_key:
            raise ValueError("OPENAI_API_KEY must be set to use OpenAIVLM")
        self._client = client or AsyncOpenAI(api_key=resolved_key)

    async def generate(
        self,
        system_prompt: str,
        user_messages: list[dict],
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
    ) -> str:
        """Call the Responses API with retry handling for transient failures."""
        payload = {
            "model": self.model,
            "instructions": system_prompt,
            "input": [{"role": "user", "content": self._to_openai_content(user_messages)}],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["parallel_tool_calls"] = True

        last_error: Exception | None = None
        for attempt, delay in enumerate((1, 2, 4), start=1):
            try:
                response = await self._client.responses.create(**payload)
                output_text = getattr(response, "output_text", None)
                if output_text:
                    return output_text
                return self._extract_text(response.output)
            except (RateLimitError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
                last_error = exc
                if not self._should_retry(exc) or attempt == 3:
                    raise
                await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _to_openai_content(user_messages: list[dict]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        for item in user_messages:
            if item["type"] == "text":
                content.append({"type": "input_text", "text": item["text"]})
            elif item["type"] == "image":
                content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{item['data']}",
                        "detail": item.get("detail", "auto"),
                    }
                )
            else:
                raise ValueError(f"Unsupported message item type: {item['type']}")
        return content

    @staticmethod
    def _should_retry(exc: Exception) -> bool:
        if isinstance(exc, (RateLimitError, APIConnectionError, APITimeoutError)):
            return True
        if isinstance(exc, APIStatusError):
            status_code = getattr(exc, "status_code", None)
            return status_code == 429 or (status_code is not None and status_code >= 500)
        return False

    @staticmethod
    def _extract_text(output_items: list[Any]) -> str:
        chunks: list[str] = []
        for item in output_items:
            if getattr(item, "type", None) != "message":
                continue
            for content_item in getattr(item, "content", []):
                if hasattr(content_item, "text") and content_item.text:
                    chunks.append(content_item.text)
                elif isinstance(content_item, dict) and content_item.get("text"):
                    chunks.append(content_item["text"])
        if not chunks:
            raise ValueError("OpenAI response did not contain textual output")
        return "\n".join(chunks)


def create_vlm(provider: str, model: str, **kwargs: Any) -> VLMInterface:
    """Factory for configured VLM providers."""
    normalized = provider.lower()
    if normalized == "openai":
        return OpenAIVLM(model=model, **kwargs)
    raise NotImplementedError(f"Provider '{provider}' is not implemented in Sprint 1")
