"""CLI entrypoint for the configured remote DeepPrep preprocessing tool."""
from __future__ import annotations

import argparse
import json

from clinagent.families.neuro.tools import DeepPrepPreprocessingTool


def main() -> None:
    parser = argparse.ArgumentParser(description="Run or inspect the remote DeepPrep preprocessing tool")
    parser.add_argument("--runner", choices=["docker", "singularity", "apptainer"], help="Remote container runner")
    parser.add_argument("--sif-path", help="Remote DeepPrep SIF image path for Singularity/Apptainer")
    sub = parser.add_subparsers(dest="operation", required=True)

    sub.add_parser("health", help="Check the configured remote DeepPrep wrapper")

    run = sub.add_parser("run", help="Run or dry-run DeepPrep")
    run.add_argument("--bids-dir", required=True, help="Absolute BIDS input directory on the remote server")
    run.add_argument("--output-dir", required=True, help="Absolute DeepPrep output directory on the remote server")
    run.add_argument("--fs-license-file", required=True, help="Absolute FreeSurfer license file on the remote server")
    run.add_argument("--participant-label", nargs="+")
    run.add_argument("--bold-task-type")
    run.add_argument("--mode", default="full", choices=["full", "anat_only", "bold_only"])
    run.add_argument("--device", default="auto")
    run.add_argument("--job-id")
    run.add_argument("--execute", action="store_true", help="Actually start DeepPrep; default is dry-run")
    run.add_argument("--foreground", action="store_true", help="Run in foreground when --execute is set")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--skip-bids-validation", action="store_true")

    status = sub.add_parser("status", help="Inspect a remote DeepPrep job")
    status.add_argument("job_id")

    manifest = sub.add_parser("manifest", help="Build a manifest from a DeepPrep output directory")
    manifest.add_argument("--output-dir", required=True)
    manifest.add_argument("--participant-label", nargs="+")

    args = parser.parse_args()
    tool = DeepPrepPreprocessingTool()
    try:
        if args.operation == "health":
            result = tool.run(operation="health", runner=args.runner, sif_path=args.sif_path)
        elif args.operation == "run":
            result = tool.run(
                operation="run",
                bids_dir=args.bids_dir,
                output_dir=args.output_dir,
                fs_license_file=args.fs_license_file,
                participant_label=args.participant_label,
                bold_task_type=args.bold_task_type,
                mode=args.mode,
                device=args.device,
                runner=args.runner,
                sif_path=args.sif_path,
                job_id=args.job_id,
                dry_run=not args.execute,
                detach=not args.foreground,
                resume=args.resume,
                skip_bids_validation=args.skip_bids_validation,
            )
        elif args.operation == "status":
            result = tool.run(operation="status", job_id=args.job_id, runner=args.runner, sif_path=args.sif_path)
        else:
            result = tool.run(
                operation="manifest",
                output_dir=args.output_dir,
                participant_label=args.participant_label,
                runner=args.runner,
                sif_path=args.sif_path,
            )
    except Exception as exc:
        result = {"status": "error", "error": str(exc)}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
