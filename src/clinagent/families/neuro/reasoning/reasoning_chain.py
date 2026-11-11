"""Orchestrates the multi-step reasoning chain for report generation."""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass

from clinagent.families.neuro.config import NeuroAgentConfig
from clinagent.families.neuro.reasoning.prompt_templates import PromptTemplates
from clinagent.families.neuro.reasoning.vlm_interface import VLMInterface


@dataclass
class ReasoningResult:
    """Complete output of a reasoning chain run."""

    config: str
    step1_observations: str | None
    step2_integration: str | None
    final_report: str
    tool_outputs: dict | None
    model: str
    num_slices: int


class ReasoningChain:
    """Run the configured neuro-report generation path."""

    SYSTEM_PROMPT = "You are an experienced neuroradiologist."
    _SECTION_ORDER = (
        "CLINICAL INFORMATION",
        "TECHNIQUE",
        "FINDINGS",
        "IMPRESSION",
    )
    _DATE_PLACEHOLDER_RE = re.compile(r"\[date_[^\]]+\]", flags=re.IGNORECASE)

    def __init__(self, vlm: VLMInterface, config: NeuroAgentConfig):
        self.vlm = vlm
        self.config = config
        self.templates = PromptTemplates()

    async def run(
        self,
        slices_png: list[bytes],
        slices_metadata: list[dict],
        tool_outputs: dict | None,
        patient_metadata: dict,
        reasoning_mode: str = "full_agent",
    ) -> ReasoningResult:
        """Dispatch to the requested reasoning mode."""
        if reasoning_mode == "vanilla":
            return await self._run_vanilla(slices_png, slices_metadata, patient_metadata)
        if reasoning_mode == "seg_overlay":
            return await self._run_seg_overlay(slices_png, slices_metadata, patient_metadata)
        if reasoning_mode == "tool_output":
            if tool_outputs is None:
                raise ValueError("tool_outputs are required for tool_output mode")
            return await self._run_tool_output(slices_png, slices_metadata, tool_outputs, patient_metadata)
        if reasoning_mode == "full_agent":
            if tool_outputs is None:
                raise ValueError("tool_outputs are required for full_agent mode")
            return await self._run_full_agent(slices_png, slices_metadata, tool_outputs, patient_metadata)
        if reasoning_mode == "dynamic":
            return await self._run_dynamic(slices_png, slices_metadata, patient_metadata)
        raise ValueError(f"Unsupported reasoning mode: {reasoning_mode}")

    async def _run_vanilla(
        self,
        slices_png: list[bytes],
        slices_metadata: list[dict],
        patient_metadata: dict,
    ) -> ReasoningResult:
        prompt = self.templates.render_vanilla(
            patient_age=patient_metadata.get("age"),
            patient_sex=patient_metadata.get("sex"),
            clinical_indication=patient_metadata.get("indication", "Brain MRI for clinical evaluation"),
            sequences=patient_metadata.get("sequences", ["T1w"]),
        )
        final_report = await self.vlm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_messages=[{"type": "text", "text": prompt}, *self._image_messages(slices_png)],
            temperature=self.config.vlm_temperature,
            max_tokens=self.config.vlm_max_tokens,
        )
        return self._result("vanilla", self._normalize_report(final_report), len(slices_metadata))

    async def _run_seg_overlay(
        self,
        slices_png: list[bytes],
        slices_metadata: list[dict],
        patient_metadata: dict,
    ) -> ReasoningResult:
        prompt = self.templates.render_seg_overlay(
            patient_age=patient_metadata.get("age"),
            patient_sex=patient_metadata.get("sex"),
            clinical_indication=patient_metadata.get("indication", "Brain MRI for clinical evaluation"),
            sequences=patient_metadata.get("sequences", ["T1w"]),
        )
        final_report = await self.vlm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_messages=[{"type": "text", "text": prompt}, *self._image_messages(slices_png)],
            temperature=self.config.vlm_temperature,
            max_tokens=self.config.vlm_max_tokens,
        )
        return self._result("seg_overlay", self._normalize_report(final_report), len(slices_metadata))

    async def _run_tool_output(
        self,
        slices_png: list[bytes],
        slices_metadata: list[dict],
        tool_outputs: dict,
        patient_metadata: dict,
    ) -> ReasoningResult:
        tool_outputs_json = json.dumps(tool_outputs, indent=2, sort_keys=True)
        prompt = self.templates.render_single_step(
            num_slices=len(slices_metadata),
            tool_outputs_json=tool_outputs_json,
            patient_age=patient_metadata.get("age"),
            patient_sex=patient_metadata.get("sex"),
            clinical_indication=patient_metadata.get("indication", "Brain MRI for clinical evaluation"),
            sequences=patient_metadata.get("sequences", ["T1w"]),
        )
        final_report = await self.vlm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_messages=[{"type": "text", "text": prompt}, *self._image_messages(slices_png)],
            temperature=self.config.vlm_temperature,
            max_tokens=self.config.vlm_max_tokens,
        )
        return self._result(
            "tool_output",
            self._normalize_report(final_report),
            len(slices_metadata),
            tool_outputs=tool_outputs,
        )

    async def _run_full_agent(
        self,
        slices_png: list[bytes],
        slices_metadata: list[dict],
        tool_outputs: dict,
        patient_metadata: dict,
    ) -> ReasoningResult:
        tool_outputs_json = json.dumps(tool_outputs, indent=2, sort_keys=True)
        step1_prompt = self.templates.render_step1(slices_metadata, tool_outputs_json)
        step1_output = await self.vlm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_messages=[{"type": "text", "text": step1_prompt}, *self._image_messages(slices_png)],
            temperature=self.config.vlm_temperature,
            max_tokens=self.config.vlm_max_tokens,
        )

        step2_prompt = self.templates.render_step2(
            step1_output=step1_output,
            tool_summary=self._tool_summary(tool_outputs),
        )
        step2_output = await self.vlm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_messages=[{"type": "text", "text": step2_prompt}],
            temperature=self.config.vlm_temperature,
            max_tokens=self.config.vlm_max_tokens,
        )

        step3_prompt = self.templates.render_step3(
            step2_output=step2_output,
            patient_age=patient_metadata.get("age"),
            patient_sex=patient_metadata.get("sex"),
            clinical_indication=patient_metadata.get("indication", "Brain MRI for clinical evaluation"),
            sequences=patient_metadata.get("sequences", ["T1w"]),
        )
        final_report = await self.vlm.generate(
            system_prompt=self.SYSTEM_PROMPT,
            user_messages=[{"type": "text", "text": step3_prompt}],
            temperature=self.config.vlm_temperature,
            max_tokens=self.config.vlm_max_tokens,
        )
        return ReasoningResult(
            config="full_agent",
            step1_observations=step1_output,
            step2_integration=step2_output,
            final_report=self._normalize_report(final_report),
            tool_outputs=tool_outputs,
            model=getattr(self.vlm, "model", "unknown"),
            num_slices=len(slices_metadata),
        )

    async def _run_dynamic(
        self,
        slices_png: list[bytes],
        slices_metadata: list[dict],
        patient_metadata: dict,
    ) -> ReasoningResult:
        raise NotImplementedError("Config 5 will be implemented in Sprint 2")

    @staticmethod
    def _image_messages(slices_png: list[bytes]) -> list[dict]:
        return [
            {"type": "image", "data": base64.b64encode(image_bytes).decode("ascii")}
            for image_bytes in slices_png
        ]

    @staticmethod
    def _tool_summary(tool_outputs: dict) -> str:
        segmentation = tool_outputs.get("segmentation", {})
        volumetrics = tool_outputs.get("volumetrics", {})
        region_count = len(segmentation.get("regions", []))
        total_brain = segmentation.get("total_brain_volume_mm3")
        summary_parts = [
            f"Segmentation identified {region_count} labeled regions.",
        ]
        if total_brain is not None:
            summary_parts.append(f"Non-CSF brain volume: {float(total_brain):.1f} mm3.")
        if volumetrics.get("summary"):
            summary_parts.append(volumetrics["summary"])
        else:
            summary_parts.append("Normative volumetric interpretation was not available for this case.")
        return " ".join(summary_parts)

    def _result(
        self,
        config_name: str,
        final_report: str,
        num_slices: int,
        tool_outputs: dict | None = None,
    ) -> ReasoningResult:
        return ReasoningResult(
            config=config_name,
            step1_observations=None,
            step2_integration=None,
            final_report=final_report,
            tool_outputs=tool_outputs,
            model=getattr(self.vlm, "model", "unknown"),
            num_slices=num_slices,
        )

    @classmethod
    def _normalize_report(cls, report_text: str) -> str:
        """Coerce model output into a plain-text four-section radiology report."""
        text = report_text.replace("\r\n", "\n").strip()
        text = re.sub(r"^#+\s*Radiology Report\s*\n*", "", text, flags=re.IGNORECASE)
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                lines.append("")
                continue
            line = re.sub(r"^\s*#{1,6}\s*", "", line)
            line = re.sub(r"^\*\*(.+?)\*\*$", r"\1", line)
            line = re.sub(r"^\s*[-*]\s+", "", line)
            if line.lower().startswith("comparison") and cls._DATE_PLACEHOLDER_RE.search(line):
                lines.append("Comparison: Prior MR exam available.")
                continue
            if re.match(r"^(clinical information|technique|findings|impression)\s*:?\s*$", line, flags=re.IGNORECASE):
                section_name = re.sub(r"\s*:\s*$", "", line).upper()
                lines.append(f"{section_name}:")
            else:
                lines.append(line)
        cleaned = "\n".join(lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        section_map = cls._extract_sections(cleaned)
        if not section_map:
            return cleaned

        normalized_sections: list[str] = []
        for section_name in cls._SECTION_ORDER:
            content = section_map.get(section_name, "").strip()
            if section_name != "IMPRESSION":
                content = re.sub(
                    r"(?im)^recommend(?:ed|ation)?s?\b.*$",
                    "",
                    content,
                ).strip()
            normalized_sections.append(f"{section_name}:\n{content}".rstrip())
        return "\n\n".join(normalized_sections).strip()

    @classmethod
    def _extract_sections(cls, text: str) -> dict[str, str]:
        matches = list(
            re.finditer(
                r"(?im)^(CLINICAL INFORMATION|TECHNIQUE|FINDINGS|IMPRESSION):\s*$",
                text,
            )
        )
        if not matches:
            return {}
        sections: dict[str, str] = {}
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            sections[match.group(1).upper()] = text[start:end].strip()
        return sections
