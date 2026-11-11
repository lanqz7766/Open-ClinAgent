from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class MRRateLocalLaunchStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def study_dir(self, patient_uid: str, study_uid: str) -> Path:
        return self.root / patient_uid / study_uid

    def manifest_path(self, patient_uid: str, study_uid: str) -> Path:
        return self.study_dir(patient_uid, study_uid) / "launch_manifest.json"

    def context_path(self, patient_uid: str, study_uid: str) -> Path:
        return self.study_dir(patient_uid, study_uid) / "knowledge_context.json"

    def get_ready_launch(self, patient_uid: str, study_uid: str) -> dict[str, Any] | None:
        manifest_path = self.manifest_path(patient_uid, study_uid)
        if not manifest_path.exists():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        local_bundle = payload.get("local_bundle")
        if not isinstance(local_bundle, dict):
            return None
        image_path = Path(str(local_bundle.get("image_path") or "")).expanduser()
        if not image_path.exists():
            return None
        seg_path_value = local_bundle.get("seg_path")
        if seg_path_value:
            seg_path = Path(str(seg_path_value)).expanduser()
            if not seg_path.exists():
                return None
        return payload

    def write_launch(
        self,
        *,
        patient_uid: str,
        study_uid: str,
        image_bytes: bytes,
        seg_bytes: bytes | None,
        remote_manifest: dict[str, Any],
        knowledge_context: dict[str, Any],
    ) -> dict[str, Any]:
        study_dir = self.study_dir(patient_uid, study_uid)
        study_dir.mkdir(parents=True, exist_ok=True)

        image_path = study_dir / "image.nii.gz"
        image_path.write_bytes(image_bytes)

        seg_path: Path | None = None
        if seg_bytes is not None:
            seg_path = study_dir / "segmentation.nii.gz"
            seg_path.write_bytes(seg_bytes)

        demographics = self._extract_demographics(knowledge_context)
        local_bundle = {
            "image_path": str(image_path),
            "seg_path": str(seg_path) if seg_path else None,
            "supported_modes": ["vanilla", "seg_overlay"] if seg_path else ["vanilla"],
            "age": demographics.get("age"),
            "sex": demographics.get("sex"),
        }
        payload = {
            "ok": True,
            "patient_uid": patient_uid,
            "study_uid": study_uid,
            "local_status": "downloaded",
            "local_bundle": local_bundle,
            "knowledge_context": knowledge_context,
            "download_summary": {
                "cache_hit": False,
                "downloaded": True,
                "local_dir": str(study_dir),
            },
            "remote_manifest": remote_manifest,
        }
        self.context_path(patient_uid, study_uid).write_text(
            json.dumps(knowledge_context, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.manifest_path(patient_uid, study_uid).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def build_ready_payload(self, patient_uid: str, study_uid: str, cached: dict[str, Any]) -> dict[str, Any]:
        knowledge_context = cached.get("knowledge_context") or self._read_json(self.context_path(patient_uid, study_uid))
        local_bundle = dict(cached.get("local_bundle") or {})
        demographics = self._extract_demographics(knowledge_context if isinstance(knowledge_context, dict) else None)
        if "age" not in local_bundle:
            local_bundle["age"] = demographics.get("age")
        if "sex" not in local_bundle:
            local_bundle["sex"] = demographics.get("sex")
        return {
            "ok": True,
            "patient_uid": patient_uid,
            "study_uid": study_uid,
            "local_status": "ready_local",
            "local_bundle": local_bundle,
            "knowledge_context": knowledge_context,
            "download_summary": {
                "cache_hit": True,
                "downloaded": False,
                "local_dir": str(self.study_dir(patient_uid, study_uid)),
            },
        }

    def mark_missing(self, patient_uid: str, study_uid: str) -> dict[str, Any]:
        return {
            "ok": True,
            "patient_uid": patient_uid,
            "study_uid": study_uid,
            "local_status": "missing",
            "local_bundle": None,
            "knowledge_context": None,
            "download_summary": {
                "cache_hit": False,
                "downloaded": False,
                "local_dir": str(self.study_dir(patient_uid, study_uid)),
            },
        }

    def reset_study(self, patient_uid: str, study_uid: str) -> None:
        shutil.rmtree(self.study_dir(patient_uid, study_uid), ignore_errors=True)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _extract_demographics(knowledge_context: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(knowledge_context, dict):
            return {"age": None, "sex": None}
        study = knowledge_context.get("study")
        if not isinstance(study, dict):
            return {"age": None, "sex": None}
        age = study.get("patient_age")
        sex = study.get("patient_sex")
        try:
            normalized_age = int(age) if age is not None and str(age).strip() != "" else None
        except (TypeError, ValueError):
            normalized_age = None
        normalized_sex = str(sex).strip().upper()[:1] if sex else None
        if normalized_sex not in {"M", "F"}:
            normalized_sex = None
        return {"age": normalized_age, "sex": normalized_sex}
