"""Tool wrappers for neuro registration utilities."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from clinagent.families.neuro.registration import apply_neuro_transform, coregister_longitudinal, coregister_sequences
from clinagent.families.neuro.tools.base_tool import BaseTool


DEFAULT_REMOTE_TIMEOUT_S = 60 * 60 * 2


class RemoteRegistrationMixin:
    """Optional SSH bridge for the server-side neuro registration CLI."""

    def __init__(
        self,
        *,
        remote_host: str | None = None,
        remote_cli: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self.remote_host = (remote_host or os.getenv("CLINAGENT_NEURO_REGISTRATION_REMOTE_HOST", "")).strip()
        self.remote_cli = (
            remote_cli
            or os.getenv("CLINAGENT_NEURO_REGISTRATION_REMOTE_CLI", "")
            or "clinagent-neuro-register"
        ).strip()
        self.ssh_config = os.getenv("CLINAGENT_NEURO_REGISTRATION_SSH_CONFIG", "").strip()
        self.timeout_s = float(
            timeout_s or os.getenv("CLINAGENT_NEURO_REGISTRATION_TIMEOUT_S", DEFAULT_REMOTE_TIMEOUT_S)
        )

    def _remote_enabled(self) -> bool:
        return bool(self.remote_host)

    def _run_remote(self, *, subcommand: str, argv: list[str], operation: str) -> dict[str, Any]:
        if not self.remote_host:
            raise RuntimeError("Set CLINAGENT_NEURO_REGISTRATION_REMOTE_HOST before using remote registration.")
        if not self.remote_cli:
            raise RuntimeError("Set CLINAGENT_NEURO_REGISTRATION_REMOTE_CLI before using remote registration.")

        remote_argv = [self.remote_cli, subcommand, *argv]
        remote_command = " ".join(shlex.quote(part) for part in remote_argv)
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
        stdout = (completed.stdout or "").strip()
        try:
            payload = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            payload = {"raw_stdout": stdout}
        payload.setdefault("status", "ok" if completed.returncode == 0 else "error")
        payload.setdefault("operation", operation)
        payload.setdefault("remote_host", self.remote_host)
        payload.setdefault("remote_cli", self.remote_cli)
        payload.setdefault("returncode", completed.returncode)
        if completed.stderr.strip():
            payload["stderr"] = completed.stderr.strip()
        return payload


def _add_optional(argv: list[str], flag: str, value: Any) -> None:
    if value is not None:
        argv.extend([flag, str(value)])


def _add_no_overwrite(argv: list[str], overwrite: bool | None) -> None:
    if overwrite is False:
        argv.append("--no-overwrite")


class NeuroSequenceCoregistrationTool(RemoteRegistrationMixin, BaseTool):
    @property
    def name(self) -> str:
        return "coregister_neuro_sequences"

    @property
    def description(self) -> str:
        return "Coregister a moving neuro MRI NIfTI to a fixed/reference NIfTI and return transform, resampled image, and QC"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "fixed_image_path": {"type": "string"},
                "moving_image_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "case_id": {"type": "string"},
                "fixed_label": {"type": "string"},
                "moving_label": {"type": "string"},
                "initialization": {"type": "string", "enum": ["header", "center", "com"]},
                "method": {"type": "string", "enum": ["rigid", "translation"], "description": "Use rigid for 6-DOF alignment; translation only for coarse initialization."},
                "interpolation": {"type": "string", "enum": ["linear", "nearest"]},
                "overwrite": {"type": "boolean"},
            },
            "required": ["fixed_image_path", "moving_image_path", "output_dir"],
            "additionalProperties": False,
        }

    def run(self, **kwargs: Any) -> dict:
        if self._remote_enabled():
            argv = [
                "--fixed-image-path",
                str(kwargs["fixed_image_path"]),
                "--moving-image-path",
                str(kwargs["moving_image_path"]),
                "--output-dir",
                str(kwargs["output_dir"]),
            ]
            _add_optional(argv, "--case-id", kwargs.get("case_id"))
            _add_optional(argv, "--fixed-label", kwargs.get("fixed_label"))
            _add_optional(argv, "--moving-label", kwargs.get("moving_label"))
            _add_optional(argv, "--initialization", kwargs.get("initialization"))
            _add_optional(argv, "--method", kwargs.get("method"))
            _add_optional(argv, "--interpolation", kwargs.get("interpolation"))
            _add_no_overwrite(argv, kwargs.get("overwrite"))
            return self._run_remote(
                subcommand="coregister-sequences",
                argv=argv,
                operation="coregister_sequences",
            )
        return coregister_sequences(**kwargs)


class NeuroTransformApplicationTool(RemoteRegistrationMixin, BaseTool):
    @property
    def name(self) -> str:
        return "apply_neuro_transform"

    @property
    def description(self) -> str:
        return "Apply a stored neuro affine transform to an image or label map and resample it to a reference grid"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source_image_path": {"type": "string"},
                "reference_image_path": {"type": "string"},
                "transform_path": {"type": "string"},
                "output_image_path": {"type": "string"},
                "interpolation": {"type": "string", "enum": ["linear", "nearest"]},
                "invert": {"type": "boolean"},
                "overwrite": {"type": "boolean"},
            },
            "required": ["source_image_path", "reference_image_path", "transform_path", "output_image_path"],
            "additionalProperties": False,
        }

    def run(self, **kwargs: Any) -> dict:
        if self._remote_enabled():
            argv = [
                "--source-image-path",
                str(kwargs["source_image_path"]),
                "--reference-image-path",
                str(kwargs["reference_image_path"]),
                "--transform-path",
                str(kwargs["transform_path"]),
                "--output-image-path",
                str(kwargs["output_image_path"]),
            ]
            _add_optional(argv, "--interpolation", kwargs.get("interpolation"))
            if kwargs.get("invert") is True:
                argv.append("--invert")
            _add_no_overwrite(argv, kwargs.get("overwrite"))
            return self._run_remote(
                subcommand="apply-transform",
                argv=argv,
                operation="apply_neuro_transform",
            )
        return apply_neuro_transform(**kwargs)


class NeuroLongitudinalCoregistrationTool(RemoteRegistrationMixin, BaseTool):
    @property
    def name(self) -> str:
        return "coregister_neuro_longitudinal"

    @property
    def description(self) -> str:
        return "Coregister a follow-up neuro MRI NIfTI to a baseline NIfTI with conservative longitudinal QC"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "baseline_image_path": {"type": "string"},
                "followup_image_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "case_id": {"type": "string"},
                "baseline_label": {"type": "string"},
                "followup_label": {"type": "string"},
                "initialization": {"type": "string", "enum": ["header", "center", "com"]},
                "method": {"type": "string", "enum": ["rigid", "translation"], "description": "Rigid rotation and translation without scaling or deformation."},
                "interpolation": {"type": "string", "enum": ["linear", "nearest"]},
                "overwrite": {"type": "boolean"},
            },
            "required": ["baseline_image_path", "followup_image_path", "output_dir"],
            "additionalProperties": False,
        }

    def run(self, **kwargs: Any) -> dict:
        if self._remote_enabled():
            argv = [
                "--baseline-image-path",
                str(kwargs["baseline_image_path"]),
                "--followup-image-path",
                str(kwargs["followup_image_path"]),
                "--output-dir",
                str(kwargs["output_dir"]),
            ]
            _add_optional(argv, "--case-id", kwargs.get("case_id"))
            _add_optional(argv, "--baseline-label", kwargs.get("baseline_label"))
            _add_optional(argv, "--followup-label", kwargs.get("followup_label"))
            _add_optional(argv, "--initialization", kwargs.get("initialization"))
            _add_optional(argv, "--method", kwargs.get("method"))
            _add_optional(argv, "--interpolation", kwargs.get("interpolation"))
            _add_no_overwrite(argv, kwargs.get("overwrite"))
            return self._run_remote(
                subcommand="coregister-longitudinal",
                argv=argv,
                operation="coregister_longitudinal",
            )
        return coregister_longitudinal(**kwargs)
