"""Client-side neuro tool for the external structural segmentation service."""
from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from clinagent.platform.config import load_settings
from clinagent.families.neuro.preprocessing import prepare_nnunet_service_input
from clinagent.families.neuro.tools.base_tool import BaseTool


class NNUNetServiceClient:
    """Thin HTTP client for the standalone structural segmentation service."""

    def __init__(
        self,
        *,
        service_url: str,
        api_key: str | None = None,
        timeout_s: float = 600.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = (service_url or "").strip().rstrip("/")
        if not normalized:
            raise ValueError("Segmentation tool service is not configured")
        self.service_url = normalized
        self.api_key = (api_key or "").strip()
        self.timeout_s = timeout_s
        self.transport = transport

    def check_health(self) -> dict[str, Any]:
        return self._get_json("/health")

    def get_model_info(self) -> dict[str, Any]:
        return self._get_json("/model-info")

    def predict(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_json("/predict", payload)

    def _get_json(self, path: str) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_s, transport=self.transport, headers=self._headers()) as client:
            response = client.get(f"{self.service_url}{path}")
            response.raise_for_status()
            return dict(response.json())

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=self.timeout_s, transport=self.transport, headers=self._headers()) as client:
            response = client.post(f"{self.service_url}{path}", json=payload)
            response.raise_for_status()
            return dict(response.json())

    def _headers(self) -> dict[str, str] | None:
        if not self.api_key:
            return None
        return {"Authorization": f"Bearer {self.api_key}"}


@dataclass(frozen=True)
class RemoteSegmentationRun:
    remote_host: str
    remote_dir: str
    remote_input_path: str
    remote_output_path: str
    local_output_path: str
    local_label_schema_path: str


class NNUNetBrainSegmentationTool(BaseTool):
    """Prepare a T1 NIfTI and invoke the standalone structural segmentation service."""

    def __init__(
        self,
        *,
        service_url: str | None = None,
        timeout_s: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = load_settings()
        self.service_url = (service_url or settings.nnunet_service_url or "").strip()
        self.timeout_s = float(timeout_s if timeout_s is not None else settings.nnunet_timeout_s)
        self.transport = transport
        self._model_id_hint = settings.nnunet_model_id
        self._remote_host = (settings.segmentation_tool_remote_host or "").strip()
        self._remote_root = (settings.segmentation_tool_remote_root or "/tmp/clinagent-segmentation").strip()
        self._api_key = (settings.segmentation_tool_api_key or os.getenv("BRAIN_SEG_API_KEY", "")).strip()
        self._default_gpu_id = settings.segmentation_tool_gpu_id

    @property
    def name(self) -> str:
        return "nnunet_brain_segmentation"

    @property
    def description(self) -> str:
        return "Prepare a T1 NIfTI with LIA + basic QC, then call the structural segmentation service"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input_nifti_path": {
                    "type": "string",
                    "description": "Absolute path to the input T1 NIfTI file",
                },
                "output_seg_path": {
                    "type": "string",
                    "description": "Optional absolute path for the segmentation output NIfTI",
                },
                "prepared_input_path": {
                    "type": "string",
                    "description": "Optional absolute path for the LIA-reoriented service input",
                },
                "sequence_hint": {
                    "type": "string",
                    "description": "Optional explicit sequence label such as T1w",
                },
                "device": {
                    "type": "string",
                    "enum": ["auto", "cuda", "cpu"],
                    "description": "Preferred inference device",
                },
                "gpu_id": {
                    "type": "integer",
                    "description": "Optional GPU index when using CUDA",
                },
                "engine": {
                    "type": "string",
                    "description": "Service-side engine selector. Defaults to auto.",
                },
                "overwrite": {
                    "type": "boolean",
                    "description": "Whether the service may overwrite an existing output segmentation",
                },
                "include_model_info": {
                    "type": "boolean",
                    "description": "Include GET /model-info in the response payload",
                },
            },
            "required": ["input_nifti_path"],
            "additionalProperties": False,
        }

    def get_model_info(self) -> dict[str, Any]:
        return self._client().get_model_info()

    def check_health(self) -> dict[str, Any]:
        return self._client().check_health()

    def run(
        self,
        *,
        input_nifti_path: str,
        output_seg_path: str | None = None,
        prepared_input_path: str | None = None,
        sequence_hint: str | None = None,
        device: str = "auto",
        gpu_id: int | None = None,
        engine: str = "auto",
        overwrite: bool = True,
        include_model_info: bool = True,
    ) -> dict:
        prepared = prepare_nnunet_service_input(
            input_nifti_path,
            output_path=prepared_input_path,
            sequence_hint=sequence_hint,
            require_t1=True,
        )
        input_path = Path(input_nifti_path).expanduser().resolve()
        seg_path = Path(output_seg_path).expanduser().resolve() if output_seg_path else _default_segmentation_path(input_path)

        client = self._client()
        health = client.check_health()
        model_info = client.get_model_info() if include_model_info else None
        remote_run = self._create_remote_run(
            prepared_input_path=prepared["prepared_input_path"],
            local_output_seg_path=str(seg_path),
        )
        predict_payload = {
            "input_image": remote_run.remote_input_path if remote_run else prepared["prepared_input_path"],
            "output_seg": remote_run.remote_output_path if remote_run else str(seg_path),
            "device": device,
            "engine": engine,
            "overwrite": bool(overwrite),
            **(
                {"gpu_id": int(gpu_id if gpu_id is not None else self._default_gpu_id)}
                if (gpu_id is not None or self._default_gpu_id is not None)
                else {}
            ),
        }
        try:
            try:
                response = client.predict(predict_payload)
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(self._predict_error_message(exc)) from exc

            label_schema_path = response.get("label_schema_path")
            if not label_schema_path and model_info:
                label_schema_path = model_info.get("label_schema_path")
            if remote_run is not None:
                self._materialize_remote_results(
                    remote_run=remote_run,
                    remote_output_path=str(response.get("output_seg") or remote_run.remote_output_path),
                    remote_label_schema_path=str(label_schema_path or ""),
                )
                response["output_seg"] = remote_run.local_output_path
                label_schema_path = remote_run.local_label_schema_path
        finally:
            if remote_run is not None:
                self._cleanup_remote_run(remote_run)

        return {
            "service_url": self.service_url,
            "model_id_hint": self._model_id_hint or None,
            "preprocessing_profile": "lia_basic_qc",
            "prepared_input": prepared,
            "health": health,
            "model_info": model_info,
            "prediction": response,
            "output_seg_path": response.get("output_seg", str(seg_path)),
            "label_schema_path": label_schema_path,
            "remote_staging": {
                "enabled": remote_run is not None,
                "remote_host": remote_run.remote_host if remote_run else None,
                "remote_dir": remote_run.remote_dir if remote_run else None,
            },
        }

    def _client(self) -> NNUNetServiceClient:
        return NNUNetServiceClient(
            service_url=self.service_url,
            api_key=self._api_key,
            timeout_s=self.timeout_s,
            transport=self.transport,
        )

    def _create_remote_run(self, *, prepared_input_path: str, local_output_seg_path: str) -> RemoteSegmentationRun | None:
        if not self._remote_host:
            return None
        run_id = uuid.uuid4().hex
        remote_dir = f"{self._remote_root.rstrip('/')}/{run_id}"
        remote_input_path = f"{remote_dir}/input.nii.gz"
        remote_output_path = f"{remote_dir}/output_seg.nii.gz"
        local_output = Path(local_output_seg_path).expanduser().resolve()
        local_output.parent.mkdir(parents=True, exist_ok=True)
        base_name = local_output.name
        if base_name.endswith(".nii.gz"):
            base_name = base_name[:-7]
        else:
            base_name = local_output.stem
        local_label_schema_path = str(local_output.with_name(f"{base_name}_labels.json"))
        self._run_subprocess(["ssh", self._remote_host, f"mkdir -p '{remote_dir}'"], "create remote staging directory")
        self._run_subprocess(
            ["scp", str(Path(prepared_input_path).expanduser().resolve()), f"{self._remote_host}:{remote_input_path}"],
            "copy prepared segmentation input to remote host",
        )
        return RemoteSegmentationRun(
            remote_host=self._remote_host,
            remote_dir=remote_dir,
            remote_input_path=remote_input_path,
            remote_output_path=remote_output_path,
            local_output_path=str(local_output),
            local_label_schema_path=local_label_schema_path,
        )

    def _materialize_remote_results(
        self,
        *,
        remote_run: RemoteSegmentationRun,
        remote_output_path: str,
        remote_label_schema_path: str,
    ) -> None:
        self._run_subprocess(
            ["scp", f"{remote_run.remote_host}:{remote_output_path}", remote_run.local_output_path],
            "copy structural segmentation output back from remote host",
        )
        if remote_label_schema_path:
            self._run_subprocess(
                ["scp", f"{remote_run.remote_host}:{remote_label_schema_path}", remote_run.local_label_schema_path],
                "copy segmentation label schema back from remote host",
            )

    def _cleanup_remote_run(self, remote_run: RemoteSegmentationRun) -> None:
        try:
            self._run_subprocess(
                ["ssh", remote_run.remote_host, f"rm -rf '{remote_run.remote_dir}'"],
                "cleanup remote segmentation staging directory",
            )
        except RuntimeError:
            return

    @staticmethod
    def _run_subprocess(command: list[str], action: str) -> None:
        attempts = max(1, int(os.getenv("CLINAGENT_SEGMENTATION_SSH_RETRIES", "4")))
        delay_s = max(1.0, float(os.getenv("CLINAGENT_SEGMENTATION_SSH_RETRY_DELAY_S", "2")))
        last_detail = ""
        for attempt in range(1, attempts + 1):
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if result.returncode == 0:
                return
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            detail = stderr or stdout or f"exit code {result.returncode}"
            last_detail = detail
            lowered = detail.lower()
            is_transient = any(
                token in lowered
                for token in (
                    "kex_exchange_identification",
                    "connection reset by",
                    "connection closed",
                    "operation timed out",
                    "broken pipe",
                )
            )
            if attempt >= attempts or not is_transient:
                break
            time.sleep(delay_s)
        raise RuntimeError(f"Failed to {action}: {last_detail}")

    def _predict_error_message(self, exc: httpx.HTTPStatusError) -> str:
        message = f"{exc}"
        if exc.response.status_code >= 500 and not self._remote_host:
            return (
                f"{message}. If the segmentation tool service is running on another machine behind an SSH tunnel, "
                "configure CLINAGENT_SEGMENTATION_TOOL_REMOTE_HOST so input and output files are staged onto the "
                "service host before /predict is called."
            )
        return message


def _default_segmentation_path(input_path: Path) -> Path:
    name = input_path.name
    if name.endswith(".nii.gz"):
        stem = name[:-7]
    else:
        stem = input_path.stem
    return input_path.with_name(f"{stem}_seg.nii.gz").resolve()
