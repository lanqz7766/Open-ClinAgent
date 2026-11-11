"""CLI entrypoint for the research/demo brain tumor segmentation service tool."""
from __future__ import annotations

import argparse
import json

from clinagent.families.neuro.tools import BrainTumorSegmentationTool


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the brain tumor segmentation service tool")
    parser.add_argument("--t1n-nifti-path", help="Optional native T1 NIfTI path")
    parser.add_argument("--t1c-nifti-path", required=True, help="Contrast-enhanced T1 NIfTI path")
    parser.add_argument("--t2w-nifti-path", help="Optional T2-weighted NIfTI path")
    parser.add_argument("--t2f-nifti-path", required=True, help="FLAIR/T2-FLAIR NIfTI path")
    parser.add_argument("--output-dir", help="Optional output directory for segmentation artifacts")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"])
    parser.add_argument("--model-id", help="Optional service-side model id")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not overwrite output artifacts")
    args = parser.parse_args()

    result = BrainTumorSegmentationTool().run(
        t1n_nifti_path=args.t1n_nifti_path,
        t1c_nifti_path=args.t1c_nifti_path,
        t2w_nifti_path=args.t2w_nifti_path,
        t2f_nifti_path=args.t2f_nifti_path,
        output_dir=args.output_dir,
        device=args.device,
        model_id=args.model_id,
        overwrite=not args.no_overwrite,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
