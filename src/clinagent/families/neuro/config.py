"""Default configuration for the neuro agent module."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from clinagent.bundled_resources import bundled_dir, source_tree_dir


_NORMATIVE_TABLE_RELATIVE_PATH = Path("configs") / "normative_brain_volumes.json"


def _default_normative_table_path() -> str:
    cwd_candidate = Path.cwd() / _NORMATIVE_TABLE_RELATIVE_PATH
    if cwd_candidate.exists():
        return str(cwd_candidate)

    source_configs = source_tree_dir("configs")
    if source_configs is not None:
        source_candidate = source_configs / "normative_brain_volumes.json"
        if source_candidate.exists():
            return str(source_candidate)

    bundled_configs = bundled_dir("configs")
    if bundled_configs is not None:
        bundled_candidate = bundled_configs / "normative_brain_volumes.json"
        if bundled_candidate.exists():
            return str(bundled_candidate)

    return str(_NORMATIVE_TABLE_RELATIVE_PATH)


@dataclass
class NeuroAgentConfig:
    """Central configuration for the neuro-radiology agent pipeline.

    Controls slice selection, VLM provider, reasoning mode, and tool settings.
    All fields have sensible defaults for the ``full_agent`` (Config 4) path.
    """

    # Slice selection
    num_slices: int = 5
    slice_planes: list[str] = field(
        default_factory=lambda: ["axial", "coronal", "sagittal"]
    )
    slice_output_size: tuple[int, int] = (512, 512)

    # VLM
    vlm_provider: str = "openai"        # "openai" | "anthropic" | "local"
    vlm_model: str = "gpt-4o"
    vlm_temperature: float = 0.2
    vlm_max_tokens: int = 4096

    # Reasoning
    reasoning_mode: str = "full_agent"   # "vanilla" | "seg_overlay" | "tool_output" | "full_agent" | "dynamic"

    # Tools
    use_precomputed_seg: bool = True
    normative_table_path: str = field(default_factory=_default_normative_table_path)

    # Evaluation
    eval_llm_model: str = "gpt-4o"
