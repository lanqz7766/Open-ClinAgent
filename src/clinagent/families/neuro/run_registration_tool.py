"""CLI entrypoint for ClinAgent neuro registration utilities."""
from __future__ import annotations

import argparse
import json

from clinagent.families.neuro.registration import apply_neuro_transform, coregister_longitudinal, coregister_sequences


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ClinAgent neuro registration utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    coreg = sub.add_parser("coregister-sequences", help="Coregister moving image to fixed image")
    coreg.add_argument("--fixed-image-path", required=True)
    coreg.add_argument("--moving-image-path", required=True)
    coreg.add_argument("--output-dir", required=True)
    coreg.add_argument("--case-id")
    coreg.add_argument("--fixed-label", default="fixed")
    coreg.add_argument("--moving-label", default="moving")
    coreg.add_argument("--initialization", default="com", choices=["header", "center", "com"])
    coreg.add_argument("--interpolation", default="linear", choices=["linear", "nearest"])
    coreg.add_argument("--no-overwrite", action="store_true")
    coreg.add_argument("--method", default="translation", choices=["translation", "rigid"])

    longitudinal = sub.add_parser("coregister-longitudinal", help="Coregister follow-up image to baseline image")
    longitudinal.add_argument("--baseline-image-path", required=True)
    longitudinal.add_argument("--followup-image-path", required=True)
    longitudinal.add_argument("--output-dir", required=True)
    longitudinal.add_argument("--case-id")
    longitudinal.add_argument("--baseline-label", default="baseline")
    longitudinal.add_argument("--followup-label", default="followup")
    longitudinal.add_argument("--initialization", default="com", choices=["header", "center", "com"])
    longitudinal.add_argument("--interpolation", default="linear", choices=["linear", "nearest"])
    longitudinal.add_argument("--no-overwrite", action="store_true")
    longitudinal.add_argument("--method", default="translation", choices=["translation", "rigid"])

    apply = sub.add_parser("apply-transform", help="Apply a stored transform")
    apply.add_argument("--source-image-path", required=True)
    apply.add_argument("--reference-image-path", required=True)
    apply.add_argument("--transform-path", required=True)
    apply.add_argument("--output-image-path", required=True)
    apply.add_argument("--interpolation", default="linear", choices=["linear", "nearest"])
    apply.add_argument("--invert", action="store_true")
    apply.add_argument("--no-overwrite", action="store_true")

    args = parser.parse_args()
    try:
        if args.command == "coregister-sequences":
            result = coregister_sequences(
                fixed_image_path=args.fixed_image_path,
                method=args.method,
                moving_image_path=args.moving_image_path,
                output_dir=args.output_dir,
                case_id=args.case_id,
                fixed_label=args.fixed_label,
                moving_label=args.moving_label,
                initialization=args.initialization,
                interpolation=args.interpolation,
                overwrite=not args.no_overwrite,
            )
        elif args.command == "coregister-longitudinal":
            result = coregister_longitudinal(
                baseline_image_path=args.baseline_image_path,
                method=args.method,
                followup_image_path=args.followup_image_path,
                output_dir=args.output_dir,
                case_id=args.case_id,
                baseline_label=args.baseline_label,
                followup_label=args.followup_label,
                initialization=args.initialization,
                interpolation=args.interpolation,
                overwrite=not args.no_overwrite,
            )
        else:
            result = apply_neuro_transform(
                source_image_path=args.source_image_path,
                reference_image_path=args.reference_image_path,
                transform_path=args.transform_path,
                output_image_path=args.output_image_path,
                interpolation=args.interpolation,
                invert=args.invert,
                overwrite=not args.no_overwrite,
            )
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
