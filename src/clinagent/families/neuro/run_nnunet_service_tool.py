"""CLI entrypoint for the local nnUNet brain segmentation service tool."""
from __future__ import annotations

import argparse
import json

from clinagent.families.neuro.tools import NNUNetBrainSegmentationTool


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local nnUNet brain segmentation service tool")
    parser.add_argument("--input-nifti-path", required=True, help="Absolute path to the input T1 NIfTI")
    parser.add_argument("--output-seg-path", help="Optional absolute path for the output segmentation NIfTI")
    parser.add_argument("--prepared-input-path", help="Optional absolute path for the LIA-reoriented input")
    parser.add_argument("--sequence-hint", default="T1w", help="Sequence hint, defaults to T1w")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--gpu-id", type=int, help="Optional GPU index")
    parser.add_argument("--engine", default="custom", help="Service engine selector")
    parser.add_argument("--no-model-info", action="store_true", help="Skip GET /model-info")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not overwrite output segmentation")
    args = parser.parse_args()

    result = NNUNetBrainSegmentationTool().run(
        input_nifti_path=args.input_nifti_path,
        output_seg_path=args.output_seg_path,
        prepared_input_path=args.prepared_input_path,
        sequence_hint=args.sequence_hint,
        device=args.device,
        gpu_id=args.gpu_id,
        engine=args.engine,
        overwrite=not args.no_overwrite,
        include_model_info=not args.no_model_info,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
