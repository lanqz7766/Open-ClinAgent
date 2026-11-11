"""Run the neuro agent on a single MRI case. Used for development and testing."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from clinagent.families.neuro.config import NeuroAgentConfig
from clinagent.families.neuro.preprocessing import SequenceRouter, SliceSelector
from clinagent.families.neuro.reasoning import ReasoningChain, ReasoningResult, VLMInterface, create_vlm
from clinagent.families.neuro.tools import BrainSegmentationTool, VolumetricAnalysisTool


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run neuro agent on a single brain MRI")
    parser.add_argument("--nifti", required=True, help="Path to brain MRI NIfTI file")
    parser.add_argument("--seg", default=None, help="Path to segmentation NIfTI file")
    parser.add_argument("--age", type=int, default=None, help="Patient age")
    parser.add_argument("--sex", choices=["M", "F"], default=None)
    parser.add_argument("--indication", default="Brain MRI for clinical evaluation")
    parser.add_argument(
        "--mode",
        default="full_agent",
        choices=["vanilla", "seg_overlay", "tool_output", "full_agent", "dynamic"],
    )
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--num-slices", type=int, default=5)
    parser.add_argument("--output", default=None, help="Save report to file")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.mode in {"seg_overlay", "tool_output", "full_agent"} and not args.seg:
        raise ValueError(f"--seg is required when mode is '{args.mode}'")


async def run_single_case(
    nifti_path: str,
    age: int | None,
    sex: str | None,
    indication: str = "Brain MRI for clinical evaluation",
    mode: str = "full_agent",
    model: str = "gpt-4o",
    num_slices: int = 5,
    seg_path: str | None = None,
    segmentation_result_override: dict | None = None,
    volumetrics_result_override: dict | None = None,
    vlm: VLMInterface | None = None,
) -> ReasoningResult:
    """Run the configured neuro pipeline and return a structured result object."""
    config = NeuroAgentConfig(num_slices=num_slices, vlm_model=model, reasoning_mode=mode)
    selector = SliceSelector(num_slices=config.num_slices, output_size=config.slice_output_size)
    slices_metadata = selector.select_slices(nifti_path)
    slices_png = [selector.render_to_png_bytes(slice_data) for slice_data in slices_metadata]

    effective_mode = mode
    demographics_available = age is not None and (sex or "").upper() in {"M", "F"}
    tool_outputs: dict | None = None
    if mode in {"tool_output", "full_agent"}:
        if seg_path is None:
            raise ValueError(f"seg_path is required when mode is '{mode}'")
        if segmentation_result_override is not None:
            segmentation_result = segmentation_result_override
        else:
            segmentation_tool = BrainSegmentationTool()
            segmentation_result = segmentation_tool.run(seg_nifti_path=seg_path)
        tool_outputs = {"segmentation": segmentation_result}
        if demographics_available:
            if volumetrics_result_override is not None:
                volumetrics_result = volumetrics_result_override
            else:
                volumetrics_tool = VolumetricAnalysisTool(config.normative_table_path)
                volumetrics_result = volumetrics_tool.run(
                    segmentation_result=segmentation_result,
                    patient_age=age,
                    patient_sex=str(sex).upper(),
                )
            tool_outputs["volumetrics"] = volumetrics_result
        elif mode == "full_agent":
            # Fall back to the segmentation-aware overlay path when normative
            # interpretation cannot be supported safely.
            effective_mode = "seg_overlay"

    if effective_mode == "seg_overlay":
        if seg_path is None:
            raise ValueError("seg_path is required for seg_overlay mode")
        slices_png = [
            selector.render_with_overlay(slice_data, seg_path)
            for slice_data in slices_metadata
        ]

    sequence_router = SequenceRouter()
    inferred_sequence = sequence_router.identify_from_filename(Path(nifti_path).name).value
    patient_metadata = {
        "age": age,
        "sex": (sex or "").upper() or None,
        "indication": indication,
        "sequences": [inferred_sequence if inferred_sequence != "unknown" else "T1w"],
    }

    chain = ReasoningChain(vlm=vlm or create_vlm(provider=config.vlm_provider, model=config.vlm_model), config=config)
    return await chain.run(
        slices_png=slices_png,
        slices_metadata=slices_metadata,
        tool_outputs=tool_outputs,
        patient_metadata=patient_metadata,
        reasoning_mode=effective_mode,
    )


async def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(args)
    result = await run_single_case(
        nifti_path=args.nifti,
        seg_path=args.seg,
        age=args.age,
        sex=args.sex,
        indication=args.indication,
        mode=args.mode,
        model=args.model,
        num_slices=args.num_slices,
    )

    print("=" * 60)
    print("GENERATED RADIOLOGY REPORT")
    print("=" * 60)
    print(f"Model: {result.model} | Config: {result.config} | Slices: {result.num_slices}")
    print("-" * 60)
    print(result.final_report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.final_report)
        print(f"\nReport saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
