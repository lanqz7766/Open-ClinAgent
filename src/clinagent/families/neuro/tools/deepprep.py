"""ClinAgent wrapper for a remote DeepPrep preprocessing CLI."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from clinagent.families.neuro.tools.base_tool import BaseTool


DEFAULT_TIMEOUT_S = 60 * 60 * 12


class DeepPrepPreprocessingTool(BaseTool):
    """Call a configured server-side DeepPrep wrapper over SSH."""

    def __init__(
        self,
        *,
        remote_host: str | None = None,
        remote_cli: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.remote_host = (remote_host or os.getenv("CLINAGENT_DEEPPREP_REMOTE_HOST", "")).strip()
        self.remote_cli = (
            remote_cli
            or os.getenv("CLINAGENT_DEEPPREP_REMOTE_CLI", "")
            or "clinagent-deepprep"
        ).strip()
        self.ssh_config = os.getenv("CLINAGENT_DEEPPREP_SSH_CONFIG", "").strip()
        self.timeout_s = float(timeout_s or os.getenv("CLINAGENT_DEEPPREP_TIMEOUT_S", DEFAULT_TIMEOUT_S))

    @property
    def name(self) -> str:
        return "deepprep_neuro_preprocessing"

    @property
    def description(self) -> str:
        return "Run or inspect DeepPrep neuro MRI preprocessing on a configured remote server"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["health", "run", "status", "manifest"],
                    "description": "Operation to perform.",
                },
                "bids_dir": {"type": "string", "description": "Absolute BIDS input directory on the remote server."},
                "output_dir": {"type": "string", "description": "Absolute DeepPrep output directory on the remote server."},
                "fs_license_file": {"type": "string", "description": "Absolute FreeSurfer license file on the remote server."},
                "participant_label": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Subject labels, with or without sub- prefix.",
                },
                "bold_task_type": {"type": "string", "description": "BOLD task label, for example rest."},
                "mode": {
                    "type": "string",
                    "enum": ["full", "anat_only", "bold_only"],
                    "description": "DeepPrep processing mode.",
                },
                "device": {"type": "string", "description": "DeepPrep device: auto, cpu, or GPU index."},
                "runner": {
                    "type": "string",
                    "enum": ["docker", "singularity", "apptainer"],
                    "description": "Remote container runner.",
                },
                "sif_path": {
                    "type": "string",
                    "description": "Absolute DeepPrep SIF path on the remote server for Singularity/Apptainer.",
                },
                "job_id": {"type": "string", "description": "Job id for status lookup."},
                "dry_run": {"type": "boolean", "description": "Build and record the command without running DeepPrep."},
                "detach": {"type": "boolean", "description": "Run in the background and return job metadata immediately."},
                "resume": {"type": "boolean", "description": "Resume an interrupted DeepPrep job."},
                "skip_bids_validation": {"type": "boolean", "description": "Skip BIDS validation."},
            },
            "required": ["operation"],
            "additionalProperties": False,
        }

    def check_health(self) -> dict[str, Any]:
        return self.run(operation="health")

    def run(
        self,
        *,
        operation: str,
        bids_dir: str | None = None,
        output_dir: str | None = None,
        fs_license_file: str | None = None,
        participant_label: list[str] | None = None,
        bold_task_type: str | None = None,
        mode: str = "full",
        device: str = "auto",
        runner: str | None = None,
        sif_path: str | None = None,
        job_id: str | None = None,
        dry_run: bool = True,
        detach: bool = True,
        resume: bool = False,
        skip_bids_validation: bool = False,
    ) -> dict:
        if not self.remote_host:
            raise RuntimeError("Set CLINAGENT_DEEPPREP_REMOTE_HOST before using DeepPrep preprocessing.")
        if not self.remote_cli:
            raise RuntimeError("Set CLINAGENT_DEEPPREP_REMOTE_CLI before using DeepPrep preprocessing.")

        argv = [self.remote_cli]
        if runner:
            argv.extend(["--runner", runner])
        if sif_path:
            argv.extend(["--sif-path", sif_path])
        argv.append(operation)
        if operation == "run":
            if not bids_dir or not output_dir or not fs_license_file:
                raise ValueError("run requires bids_dir, output_dir, and fs_license_file.")
            argv.extend(["--bids-dir", bids_dir, "--output-dir", output_dir, "--fs-license-file", fs_license_file])
            if participant_label:
                argv.append("--participant-label")
                argv.extend(str(item) for item in participant_label)
            if bold_task_type:
                argv.extend(["--bold-task-type", bold_task_type])
            argv.extend(["--mode", mode or "full", "--device", device or "auto"])
            if dry_run:
                argv.append("--dry-run")
            if detach and not dry_run:
                argv.append("--detach")
            if resume:
                argv.append("--resume")
            if skip_bids_validation:
                argv.append("--skip-bids-validation")
            if job_id:
                argv.extend(["--job-id", job_id])
        elif operation == "status":
            if not job_id:
                raise ValueError("status requires job_id.")
            argv.append(job_id)
        elif operation == "manifest":
            if not output_dir:
                raise ValueError("manifest requires output_dir.")
            argv.extend(["--output-dir", output_dir])
            if participant_label:
                argv.append("--participant-label")
                argv.extend(str(item) for item in participant_label)
        elif operation != "health":
            raise ValueError(f"Unsupported DeepPrep operation: {operation}")

        remote_command = " ".join(shlex.quote(part) for part in argv)
        ssh_argv = ["ssh", "-q"]
        if self.ssh_config:
            ssh_argv.extend(["-F", self.ssh_config])
        ssh_argv.extend([self.remote_host, remote_command])
        completed = subprocess.run(
            ssh_argv,
            check=False,
            text=True,
            capture_output=True,
            timeout=self.timeout_s,
        )
        output = (completed.stdout or "").strip()
        try:
            payload = json.loads(output) if output else {}
        except json.JSONDecodeError:
            payload = {"raw_stdout": output}
        payload.setdefault("operation", operation)
        payload.setdefault("remote_host", self.remote_host)
        payload.setdefault("remote_cli", self.remote_cli)
        payload.setdefault("returncode", completed.returncode)
        if completed.stderr.strip():
            payload["stderr"] = completed.stderr.strip()
        if completed.returncode != 0 and payload.get("status") not in {"dry_run", "ok"}:
            payload.setdefault("status", "error")
        return payload
