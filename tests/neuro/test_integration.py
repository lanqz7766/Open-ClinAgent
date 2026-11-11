from __future__ import annotations

from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from clinagent.families.neuro.run_single import run_single_case
from clinagent.families.neuro.reasoning.reasoning_chain import ReasoningChain


def _write_nifti(path: Path, data: np.ndarray) -> Path:
    image = nib.Nifti1Image(data.astype(np.float32), np.eye(4))
    nib.save(image, str(path))
    return path


class _FakeVLM:
    def __init__(self) -> None:
        self.model = "fake-gpt"
        self.calls = []

    async def generate(self, system_prompt, user_messages, temperature=0.2, max_tokens=4096, tools=None) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_messages": user_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": tools,
            }
        )
        call_index = len(self.calls)
        if call_index == 1:
            return "Observed mild bilateral hippocampal volume loss."
        if call_index == 2:
            return "Key positive findings: mild bilateral hippocampal atrophy. Confidence level: moderate."
        return (
            "CLINICAL INFORMATION:\nMemory change.\n\n"
            "TECHNIQUE:\nMRI of the brain.\n\n"
            "FINDINGS:\nMild bilateral hippocampal volume loss.\n\n"
            "IMPRESSION:\n1. Mild bilateral hippocampal volume loss."
        )


@pytest.mark.asyncio
async def test_run_single_case_full_agent_returns_structured_report(tmp_path: Path) -> None:
    volume = np.random.rand(32, 32, 32)
    seg = np.zeros((32, 32, 32), dtype=np.int16)
    seg.ravel()[:320] = 17
    seg.ravel()[320:640] = 53
    seg.ravel()[640:960] = 3
    seg.ravel()[960:1120] = 42

    nifti_path = _write_nifti(tmp_path / "sub-001_T1w.nii.gz", volume)
    seg_path = _write_nifti(tmp_path / "sub-001_seg.nii.gz", seg)
    fake_vlm = _FakeVLM()

    result = await run_single_case(
        nifti_path=str(nifti_path),
        seg_path=str(seg_path),
        age=72,
        sex="M",
        indication="Memory change",
        mode="full_agent",
        model="gpt-4o",
        num_slices=3,
        vlm=fake_vlm,
    )

    assert result.config == "full_agent"
    assert result.model == "fake-gpt"
    assert result.num_slices == 3
    assert result.step1_observations is not None
    assert result.step2_integration is not None
    assert "CLINICAL INFORMATION" in result.final_report
    assert "TECHNIQUE" in result.final_report
    assert "FINDINGS" in result.final_report
    assert "IMPRESSION" in result.final_report
    assert "volumetrics" in result.tool_outputs
    assert len(fake_vlm.calls) == 3


def test_reasoning_chain_normalizes_markdown_report() -> None:
    raw = (
        "## Radiology Report\n\n"
        "### CLINICAL INFORMATION\n"
        "- Brain MRI for clinical evaluation\n\n"
        "### TECHNIQUE\n"
        "- MRI of the brain.\n\n"
        "### FINDINGS\n"
        "- Mild volume loss.\n"
        "Recommend follow-up imaging if symptoms worsen.\n\n"
        "### IMPRESSION\n"
        "- Mild volume loss."
    )

    normalized = ReasoningChain._normalize_report(raw)

    assert normalized.startswith("CLINICAL INFORMATION:")
    assert "## Radiology Report" not in normalized
    assert "### CLINICAL INFORMATION" not in normalized
    assert "Recommend follow-up imaging" not in normalized
    assert "IMPRESSION:" in normalized


def test_reasoning_chain_rewrites_placeholder_comparison_dates() -> None:
    raw = (
        "CLINICAL INFORMATION:\nMemory change.\n\n"
        "TECHNIQUE:\nMRI of the brain.\n\n"
        "FINDINGS:\nComparison: MR exam dated [date_1].\nMild volume loss.\n\n"
        "IMPRESSION:\n1. Mild volume loss."
    )

    normalized = ReasoningChain._normalize_report(raw)

    assert "Comparison: MR exam dated [date_1]." not in normalized
    assert "Comparison: Prior MR exam available." in normalized
