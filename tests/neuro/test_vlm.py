from __future__ import annotations

import httpx
import pytest
from openai import RateLimitError

from clinagent.families.neuro.reasoning import OpenAIVLM, PromptTemplates


class _FakeResponse:
    def __init__(self, text: str):
        self.output_text = text
        self.output = []


class _CaptureResponsesAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class _FakeClient:
    def __init__(self, responses):
        self.responses = _CaptureResponsesAPI(responses)


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError("rate limited", response=response, body=None)


@pytest.mark.asyncio
async def test_openai_vlm_converts_text_and_image_messages() -> None:
    fake_client = _FakeClient([_FakeResponse("ok")])
    vlm = OpenAIVLM(model="gpt-4o", client=fake_client)

    result = await vlm.generate(
        system_prompt="system",
        user_messages=[
            {"type": "text", "text": "hello"},
            {"type": "image", "data": "YWJj"},
        ],
        tools=[{"type": "function", "name": "demo", "description": "demo", "parameters": {"type": "object"}}],
    )

    assert result == "ok"
    call = fake_client.responses.calls[0]
    assert call["instructions"] == "system"
    assert call["input"][0]["content"][0] == {"type": "input_text", "text": "hello"}
    assert call["input"][0]["content"][1]["type"] == "input_image"
    assert call["input"][0]["content"][1]["image_url"] == "data:image/png;base64,YWJj"
    assert call["tools"][0]["name"] == "demo"


@pytest.mark.asyncio
async def test_openai_vlm_retries_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient([_rate_limit_error(), _FakeResponse("recovered")])
    vlm = OpenAIVLM(model="gpt-4o", client=fake_client)

    recorded_delays = []

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    monkeypatch.setattr("clinagent.families.neuro.reasoning.vlm_interface.asyncio.sleep", fake_sleep)

    result = await vlm.generate(
        system_prompt="system",
        user_messages=[{"type": "text", "text": "hello"}],
    )

    assert result == "recovered"
    assert recorded_delays == [1]
    assert len(fake_client.responses.calls) == 2


def test_prompt_templates_render_without_errors() -> None:
    templates = PromptTemplates()

    assert "representative slices" in templates.render_step1(
        slices_metadata=[{"description": "Axial slice"}],
        tool_outputs_json="{}",
    )
    assert "Quantitative Data Summary" in templates.render_step2("step1", "summary")
    assert "CLINICAL INFORMATION" in templates.render_step3("step2", 72, "M", "Memory change", ["T1w"])
    assert "Automated Analysis Results" in templates.render_single_step(5, "{}", 72, "M", "Memory change")
    assert "based only on the brain MRI images provided" in templates.render_vanilla(72, "M", "Memory change")
