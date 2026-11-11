from __future__ import annotations

import json
import time
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest
from fastapi.testclient import TestClient

import clinagent.families.neuro.brain_tumor_demo as brain_tumor_module
from clinagent.families.neuro.brain_tumor_demo import (
    BrainTumorDemoStore,
    classify_series_for_tumor_modality,
    suggest_modality_mapping,
)
from clinagent.families.neuro.tools.tumor_segmentation import _harmonize_modalities_to_reference


def _write_nifti(path: Path, data: np.ndarray) -> Path:
    nib.save(nib.Nifti1Image(data, np.eye(4)), str(path))
    return path


@pytest.mark.parametrize("metadata,expected", [
    ({"id": "20260101"}, None),
    ({"id": "visit_1", "scan_date": "2026-01-01"}, "2026-01-01"),
    ({"id": "visit_1", "study_date": "20260101"}, "20260101"),
    ({"id": "visit_1", "date": "2026-01-01"}, "2026-01-01"),
])
def test_registry_visit_date_uses_metadata_not_timepoint_id(tmp_path, metadata, expected):
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")
    point = store._registry_point_from_session(
        case={"title": "Synthetic"}, case_id="test", timepoint=metadata,
        timepoint_index=0, session={"session_id": "test-session"}, provenance="test",
    )
    assert point["scanDate"] == expected


def test_registry_relative_day_keeps_origin_without_inventing_calendar_date(tmp_path):
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")
    point = store._registry_point_from_session(
        case={"title": "Synthetic"}, case_id="test",
        timepoint={"id": "visit_2", "relative_day": 56.40625, "relative_day_origin": "first scan"},
        timepoint_index=1, session={"session_id": "test-session"}, provenance="test",
    )
    assert point["relativeDay"] == 56.40625
    assert point["relativeDayOrigin"] == "first scan"
    assert point["scanDate"] is None


def _write_registry_cache(
    asset_root: Path,
    *,
    registry_id: str,
    case_id: str,
    timepoint_id: str,
    model_id: str,
    volumes: list[dict[str, float | str]],
) -> None:
    session_id = brain_tumor_module._registry_cache_session_id(
        registry_id=registry_id,
        case_id=case_id,
        timepoint_id=timepoint_id,
        model_id=model_id,
    )
    session_root = asset_root / session_id
    output_root = session_root / "outputs"
    input_root = session_root / "input" / "nifti"
    output_root.mkdir(parents=True)
    input_root.mkdir(parents=True)
    artifacts = {
        "seg": output_root / "seg.nii.gz",
        "tumor_regions": output_root / "tumor_regions.json",
        "volumes_csv": output_root / "volumes.csv",
        "overlay_preview": output_root / "overlay_preview.png",
        "image_t1n": input_root / "image_t1n.nii.gz",
        "image_t1c": input_root / "image_t1c.nii.gz",
        "image_t2w": input_root / "image_t2w.nii.gz",
        "image_t2f": input_root / "image_t2f.nii.gz",
    }
    for path in artifacts.values():
        path.write_bytes(b"cached")
    session = {
        "ok": True,
        "session_id": session_id,
        "status": "complete",
        "source": {
            "type": "remote_case_registry",
            "registry_id": registry_id,
            "case_id": case_id,
            "timepoint_id": timepoint_id,
        },
        "service": {"model_id": model_id},
        "qc": {"warnings": []},
        "volumes": volumes,
        "artifacts": {key: str(value) for key, value in artifacts.items()},
    }
    (session_root / "session.json").write_text(json.dumps(session), encoding="utf-8")
    summary_path = asset_root / "registry_case_demo_summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        summary = {}
    cases = summary.get("cases") if isinstance(summary.get("cases"), dict) else {}
    cases[case_id] = brain_tumor_module._summarize_registry_sessions_for_demo([session])
    summary["cases"] = cases
    summary_path.write_text(json.dumps(summary), encoding="utf-8")


def test_brain_tumor_series_classifier_maps_common_mri_names() -> None:
    assert classify_series_for_tumor_modality({"description": "AX T1 POST GD"}).modality == "t1c"
    assert classify_series_for_tumor_modality({"description": "t1 axial stealth-post"}).modality == "t1c"
    assert classify_series_for_tumor_modality({"description": "Sag 3D FLAIR"}).modality == "t2f"
    assert classify_series_for_tumor_modality({"description": "T2 TSE AX"}).modality == "t2w"
    assert classify_series_for_tumor_modality({"description": "T1 MPRAGE pre"}).modality == "t1n"


def test_brain_tumor_suggested_mapping_keeps_highest_score() -> None:
    mapping = suggest_modality_mapping(
        [
            {"series_instance_uid": "low", "candidate_modality": "t1c", "candidate_score": 0.5},
            {"series_instance_uid": "high", "candidate_modality": "t1c", "candidate_score": 0.9},
            {"series_instance_uid": "flair", "candidate_modality": "t2f", "candidate_score": 0.8},
        ]
    )

    assert mapping == {"t1c": "high", "t2f": "flair"}


@pytest.mark.asyncio
async def test_brain_tumor_dicomweb_does_not_surface_generic_mock_chest_study(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        brain_tumor_module,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "imaging_connector_mode": "mock",
            },
        )(),
    )
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")

    payload = await store.search_dicom_studies(patient_id="any")

    assert payload["configured"] is False
    assert payload["studies"] == []
    assert "Mounted DICOM" in payload["message"]


def test_brain_tumor_mounted_dicom_scans_studies_and_series(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "mounted"
    study = root / "UPENN-GBM-00001" / "02-06-2002-BRAINROUTINE"
    flair = study / "2.000000-t2Flairaxial ProcessedCaPTk"
    t1c = study / "4.000000-T1postGD"
    flair.mkdir(parents=True)
    t1c.mkdir(parents=True)
    for index in range(3):
        (flair / f"1-{index:02d}.dcm").write_bytes(b"DICOM")
        (t1c / f"1-{index:02d}.dcm").write_bytes(b"DICOM")

    monkeypatch.setattr(
        brain_tumor_module,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "brain_tumor_dicom_roots": str(root),
                "brain_tumor_dicom_remote_host": "",
                "brain_tumor_dicom_dcm2niix_bin": "dcm2niix",
                "brain_tumor_dicom_scan_limit": 100,
            },
        )(),
    )
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")

    studies = store.search_mounted_dicom_studies(patient_id="UPENN-GBM-00001")
    assert studies["ok"] is True
    assert len(studies["studies"]) == 1
    assert studies["studies"][0]["series_count"] == 2

    series = store.search_mounted_dicom_series(study_ref=studies["studies"][0]["study_instance_uid"])
    assert series["suggested_mapping"]["t2f"]
    assert series["suggested_mapping"]["t1c"]


def test_brain_tumor_remote_output_filter_removes_login_banner() -> None:
    cleaned = brain_tumor_module._clean_remote_process_output(
        "!!!!This is a State Goverment Computer System.!!!!\n"
        "Unauthorized attempts to upload or otherwise alter data,\n"
        "** WARNING: connection is not using a post-quantum key exchange algorithm.\n"
        "bash: dcm2niix: command not found\n"
    )

    assert "State Goverment" not in cleaned
    assert "Unauthorized attempts" not in cleaned
    assert "post-quantum" not in cleaned
    assert cleaned == "bash: dcm2niix: command not found"


def test_brain_tumor_service_inputs_resample_to_t1c_grid(tmp_path: Path) -> None:
    t1c = _write_nifti(tmp_path / "t1c.nii.gz", np.ones((8, 8, 8), dtype=np.float32))
    moving_img = nib.Nifti1Image(np.ones((4, 8, 8), dtype=np.float32), np.diag([2.0, 1.0, 1.0, 1.0]))
    moving_path = tmp_path / "t2f.nii.gz"
    nib.save(moving_img, str(moving_path))

    harmonized = _harmonize_modalities_to_reference(
        {"t1c": str(t1c), "t2f": str(moving_path)},
        output_dir=tmp_path / "outputs",
        reference_key="t1c",
    )

    assert harmonized["t1c"] == str(t1c)
    assert nib.load(harmonized["t2f"]).shape == (8, 8, 8)
    assert np.allclose(nib.load(harmonized["t2f"]).affine, nib.load(str(t1c)).affine)


@pytest.mark.asyncio
async def test_brain_tumor_dicom_series_query_uses_mocked_connector(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class FakeSeries:
        study_instance_uid = "study-1"
        series_instance_uid = "series-t1c"
        modality = "MR"
        description = "T1 post contrast"
        instance_count = 140
        metadata = {"source": "fake"}

    class FakeConnector:
        async def search_series(self, *, study_instance_uid: str, modality: str | None = None):
            assert study_instance_uid == "study-1"
            assert modality == "MR"
            return [FakeSeries()]

        async def get_series_metadata(self, *, study_instance_uid: str, series_instance_uid: str):
            return {"SeriesDescription": "T1 post contrast"}

    monkeypatch.setattr(brain_tumor_module, "_dicom_connector", lambda: FakeConnector())
    store = BrainTumorDemoStore(asset_root=tmp_path)

    payload = await store.search_dicom_series(study_instance_uid="study-1")

    assert payload["ok"] is True
    assert payload["series"][0]["candidate_modality"] == "t1c"
    assert payload["suggested_mapping"]["t1c"] == "series-t1c"


def test_brain_tumor_store_blocks_missing_flair(tmp_path: Path) -> None:
    store = BrainTumorDemoStore(asset_root=tmp_path)
    t1c = _write_nifti(tmp_path / "t1c.nii.gz", np.zeros((8, 8, 8), dtype=np.float32))

    with pytest.raises(ValueError, match="missing: t1n, t2w, t2f"):
        store.analyze_nifti_paths(modality_paths={"t1c": str(t1c)})


def test_registry_rerun_job_uses_selected_visit_and_preserves_baseline_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        brain_tumor_module,
        "_load_case_registry",
        lambda: {
            "id": "registry-test",
            "model_id": "model-test",
            "cases": [
                {
                    "id": "case-test",
                    "title": "Test case",
                    "timepoints": [
                        {"id": "visit-1", "modalities": {}},
                        {"id": "visit-2", "modalities": {}},
                    ],
                }
            ],
        },
    )
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")
    calls: list[dict] = []

    def fake_rerun(**kwargs):
        calls.append(kwargs)
        return {
            "ok": True,
            "session_id": "private-rerun-session",
            "volumes": [],
            "viewer_assets": {"modality_volume_urls": {}, "segmentation_url": "/seg.nii.gz"},
        }

    monkeypatch.setattr(store, "_run_remote_registry_timepoint", fake_rerun)
    stages: list[str] = []
    result = store.run_registry_segment_job(
        job_id="job-rerun",
        case_id="case-test",
        timepoint_ids=["visit-2"],
        force_rerun=True,
        on_progress=lambda stage, _result: stages.append(stage),
    )

    assert result["status"] == "completed"
    assert result["total_count"] == 1
    assert result["visits"][0]["timepoint_id"] == "visit-2"
    assert calls[0]["force_rerun"] is True
    assert calls[0]["run_id"] == "job-rerun"
    assert stages == ["preparing", "segmenting", "materializing", "finalizing", "complete"]

    baseline_id = brain_tumor_module._registry_cache_session_id(
        registry_id="registry-test",
        case_id="case-test",
        timepoint_id="visit-2",
        model_id="model-test",
    )
    rerun_id = brain_tumor_module._registry_rerun_session_id(
        registry_id="registry-test",
        case_id="case-test",
        timepoint_id="visit-2",
        model_id="model-test",
        run_id="job-rerun",
    )
    assert rerun_id != baseline_id


def test_brain_tumor_store_creates_session_root_with_custom_output_dir(tmp_path: Path) -> None:
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")
    t1n = _write_nifti(tmp_path / "t1n.nii.gz", np.ones((8, 8, 8), dtype=np.float32))
    t1c = _write_nifti(tmp_path / "t1c.nii.gz", np.ones((8, 8, 8), dtype=np.float32))
    t2w = _write_nifti(tmp_path / "t2w.nii.gz", np.ones((8, 8, 8), dtype=np.float32))
    t2f = _write_nifti(tmp_path / "t2f.nii.gz", np.ones((8, 8, 8), dtype=np.float32))
    seg = _write_nifti(tmp_path / "seg.nii.gz", np.zeros((8, 8, 8), dtype=np.uint8))

    session = store.analyze_nifti_paths(
        modality_paths={"t1n": str(t1n), "t1c": str(t1c), "t2w": str(t2w), "t2f": str(t2f)},
        output_dir=tmp_path / "custom-output",
        precomputed_seg_path=str(seg),
    )

    assert (tmp_path / "derived" / session["session_id"] / "session.json").exists()
    assert "modality_paths" not in session


def test_brain_tumor_longitudinal_registration_returns_sanitized_qc(tmp_path: Path) -> None:
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")
    seg = _write_nifti(tmp_path / "seg.nii.gz", np.zeros((8, 8, 8), dtype=np.uint8))

    def make_session(prefix: str, offset: float) -> dict:
        data = np.zeros((8, 8, 8), dtype=np.float32)
        data[2:5, 2:5, 2:5] = 1.0 + offset
        affine = np.eye(4)
        affine[:3, 3] = offset
        paths = {
            "t1n": _write_nifti(tmp_path / f"{prefix}_t1n.nii.gz", data, ),
            "t1c": tmp_path / f"{prefix}_t1c.nii.gz",
            "t2w": _write_nifti(tmp_path / f"{prefix}_t2w.nii.gz", data),
            "t2f": _write_nifti(tmp_path / f"{prefix}_t2f.nii.gz", data),
        }
        nib.save(nib.Nifti1Image(data, affine), str(paths["t1c"]))
        return store.analyze_nifti_paths(
            modality_paths={key: str(value) for key, value in paths.items()},
            precomputed_seg_path=str(seg),
            patient_label=prefix,
        )

    baseline = make_session("baseline", 0.0)
    followup = make_session("followup", 1.0)

    payload = store.register_longitudinal_sessions(
        baseline_session_id=baseline["session_id"],
        followup_session_id=followup["session_id"],
    )

    assert payload["ok"] is True
    assert payload["registration"]["deformation_model"] == "rigid_6dof"
    assert payload["registration"]["nonlinear_deformation_allowed"] is False
    assert payload["registration"]["steps"][1]["status"] == "skipped"
    assert payload["registration"]["modality_volume_urls"]["t1c"].endswith("/image_t1c.nii.gz")
    cached = store._load_cached_longitudinal_registration(
        baseline_session_id=baseline["session_id"], followup_session_id=followup["session_id"])
    assert cached["run_id"] == payload["run_id"]
    assert store._load_cached_longitudinal_registration(
        baseline_session_id=baseline["session_id"], followup_session_id=followup["session_id"], bias_correction=True) is None
    assert store.get_registration_artifact(baseline["session_id"], followup["session_id"], "rigid_v1", payload["run_id"], "seg").is_file()
    with pytest.raises(KeyError):
        store.get_registration_artifact(baseline["session_id"], followup["session_id"], "rigid_v1", payload["run_id"], "../seg")
    assert "baseline_image_path" not in json.dumps(payload)
    assert "followup_image_path" not in json.dumps(payload)
    assert str(tmp_path) not in json.dumps(cached)
    mask = Path(followup["artifacts"]["seg"])
    stat = mask.stat()
    import os
    os.utime(mask, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert store._load_cached_longitudinal_registration(
        baseline_session_id=baseline["session_id"], followup_session_id=followup["session_id"]) is None


@pytest.mark.parametrize("mode", ["single", "batch"])
@pytest.mark.parametrize("in_memory", [False, True])
def test_longitudinal_alignment_rebases_relocated_inputs(
    tmp_path: Path, mode: str, in_memory: bool,
) -> None:
    store = BrainTumorDemoStore(asset_root=tmp_path / "current")
    original_metadata = {}
    for session_id, offset in [("baseline", 0), ("followup", 1)]:
        session_root = store.asset_root / session_id
        image_path = session_root / "input" / "nifti" / "image_t1c.nii.gz"
        image_path.parent.mkdir(parents=True)
        image = np.zeros((8, 8, 8), dtype=np.float32)
        image[2 + offset:5 + offset, 2:5, 2:5] = 1
        _write_nifti(image_path, image)
        old_path = tmp_path / "old-release" / session_id / "input" / "nifti" / image_path.name
        internal = {
            "session_id": session_id,
            "session_root": str(old_path.parents[2]),
            "modality_paths": {"t1c": str(old_path)},
        }
        metadata_path = session_root / "internal_paths.json"
        metadata_path.write_text(json.dumps(internal))
        original_metadata[metadata_path] = metadata_path.read_bytes()
        metadata_path.chmod(0o444)
        (session_root / "session.json").write_text(json.dumps({
            "session_id": session_id, "artifacts": {"image_t1c": str(old_path)},
        }))
        if in_memory:
            store._internal_sessions[session_id] = internal
        assert store.get_artifact_path(session_id, "image_t1c") == image_path

    if mode == "single":
        result = store.register_longitudinal_sessions(
            baseline_session_id="baseline", followup_session_id="followup",
        )
        registration = result["registration"]
    else:
        result = store.create_longitudinal_align_job(
            baseline_session_id="baseline", followup_session_ids=["followup"],
        )
        deadline = time.monotonic() + 5
        while result["status"] == "running" and time.monotonic() < deadline:
            time.sleep(0.01)
            result = store.get_longitudinal_align_job(result["job_id"])
        assert result["status"] == "completed", result
        assert result["completed_count"] == 2
        assert result["failed_count"] == 0
        registration = result["visits"][1]["registration"]

    assert np.isfinite(registration["ncc_delta"])
    assert registration["status"] == "ok"
    for path, content in original_metadata.items():
        assert path.read_bytes() == content
    assert str(tmp_path) not in json.dumps(result)


@pytest.mark.parametrize("missing_session", ["baseline", "followup"])
def test_longitudinal_missing_image_does_not_expose_storage_paths(
    tmp_path: Path, missing_session: str,
) -> None:
    store = BrainTumorDemoStore(asset_root=tmp_path / "current")
    for session_id in ("baseline", "followup"):
        image = tmp_path / f"{session_id}.nii.gz"
        if session_id != missing_session:
            _write_nifti(image, np.ones((8, 8, 8), dtype=np.float32))
        store._internal_sessions[session_id] = {"modality_paths": {"t1c": str(image)}}
    with pytest.raises(ValueError, match="T1c image is unavailable") as exc:
        store.register_longitudinal_sessions(
            baseline_session_id="baseline", followup_session_id="followup",
        )
    assert str(tmp_path) not in str(exc.value)


def test_brain_tumor_preload_examples_are_local_and_sanitized(tmp_path: Path) -> None:
    store = BrainTumorDemoStore(asset_root=tmp_path / "derived")
    example_root = tmp_path / "derived" / "preload" / "real_example" / "case-1"
    example_root.mkdir(parents=True)
    (example_root / "overlay_preview.png").write_bytes(b"png")
    (example_root / "preview_t1c.png").write_bytes(b"png")
    (example_root / "image_t1c.nii.gz").write_bytes(b"nii")
    (example_root / "seg.nii.gz").write_bytes(b"nii")
    manifest = {
        "examples": [
            {
                "id": "real_example",
                "title": "Real example",
                "source_note": "sanitized local preload",
                "points": [
                    {
                        "id": "case-1",
                        "sessionId": "case-1",
                        "label": "Case 1",
                        "role": "screening_baseline",
                        "dateLabel": "2026-01-01",
                        "reviewState": "accepted",
                        "volumes": [{"region": "enhancing_tumor", "volume_ml": 1.0}],
                    }
                ],
            }
        ]
    }
    (tmp_path / "derived" / "preload" / "real_example" / "examples.json").write_text(json.dumps(manifest))

    payload = store.get_preload_examples()
    artifact = store.get_preload_artifact_path("real_example", "case-1", "overlay_preview.png")
    modality_artifact = store.get_preload_artifact_path("real_example", "case-1", "preview_t1c.png")
    volume_artifact = store.get_preload_artifact_path("real_example", "case-1", "image_t1c.nii.gz")
    segmentation_artifact = store.get_preload_artifact_path("real_example", "case-1", "seg.nii.gz")

    assert payload["configured"] is True
    assert payload["examples"][0]["id"] == "real_example"
    assert payload["examples"][0]["points"][0]["reviewState"] == "pending"
    assert payload["examples"][0]["points"][0]["curationReviewState"] == "accepted"
    assert artifact.name == "overlay_preview.png"
    assert modality_artifact.name == "preview_t1c.png"
    assert volume_artifact.name == "image_t1c.nii.gz"
    assert segmentation_artifact.name == "seg.nii.gz"


def test_brain_tumor_registry_prioritizes_clean_cached_demo_cases(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asset_root = tmp_path / "derived"
    registry_id = "registry-test"
    model_id = "dataset802-unified-4class"
    registry = {
        "id": registry_id,
        "model_id": model_id,
        "cases": [
            {
                "id": "cavity-heavy",
                "title": "Cavity heavy",
                "dataset": "local-test",
                "timepoints": [{"id": "time1", "label": "Time 1", "modalities": {key: f"/remote/{key}.nii.gz" for key in brain_tumor_module.MODALITY_KEYS}}],
            },
            {
                "id": "clean-visible",
                "title": "Clean visible",
                "dataset": "local-test",
                "timepoints": [{"id": "time1", "label": "Time 1", "modalities": {key: f"/remote/{key}.nii.gz" for key in brain_tumor_module.MODALITY_KEYS}}],
            },
            {
                "id": "uncached",
                "title": "Uncached",
                "dataset": "local-test",
                "timepoints": [{"id": "time1", "label": "Time 1", "modalities": {key: f"/remote/{key}.nii.gz" for key in brain_tumor_module.MODALITY_KEYS}}],
            },
        ],
    }
    _write_registry_cache(
        asset_root,
        registry_id=registry_id,
        case_id="cavity-heavy",
        timepoint_id="time1",
        model_id=model_id,
        volumes=[
            {"region": "whole_tumor", "volume_ml": 24.0},
            {"region": "flair_abnormality", "volume_ml": 23.9},
            {"region": "enhancing_tumor", "volume_ml": 0.1},
            {"region": "cavity_or_post_surgical_change", "volume_ml": 30.0},
        ],
    )
    _write_registry_cache(
        asset_root,
        registry_id=registry_id,
        case_id="clean-visible",
        timepoint_id="time1",
        model_id=model_id,
        volumes=[
            {"region": "whole_tumor", "volume_ml": 33.0},
            {"region": "flair_abnormality", "volume_ml": 31.0},
            {"region": "enhancing_tumor", "volume_ml": 1.8},
            {"region": "cavity_or_post_surgical_change", "volume_ml": 1.9},
        ],
    )
    monkeypatch.setattr(brain_tumor_module, "_load_case_registry", lambda: registry)
    monkeypatch.setattr(
        brain_tumor_module,
        "load_settings",
        lambda: type("Settings", (), {"tumor_segmentation_model_id": model_id})(),
    )
    store = BrainTumorDemoStore(asset_root=asset_root)

    payload = store.get_case_registry()

    assert [case["id"] for case in payload["cases"]] == ["clean-visible", "cavity-heavy", "uncached"]
    assert payload["cases"][0]["demo_quality"]["recommended"] is True
    assert "cavity/exclusion label dominates" in payload["cases"][1]["demo_quality"]["note"]


def test_brain_tumor_registry_run_uses_local_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    asset_root = tmp_path / "derived"
    session_root = asset_root / "brain-tumor-old-success"
    output_root = session_root / "outputs"
    input_root = session_root / "input" / "nifti"
    output_root.mkdir(parents=True)
    input_root.mkdir(parents=True)
    artifacts = {
        "seg": output_root / "seg.nii.gz",
        "ground_truth_seg": output_root / "reference.nii.gz",
        "tumor_regions": output_root / "tumor_regions.json",
        "volumes_csv": output_root / "volumes.csv",
        "overlay_preview": output_root / "overlay_preview.png",
        "image_t1n": input_root / "image_t1n.nii.gz",
        "image_t1c": input_root / "image_t1c.nii.gz",
        "image_t2w": input_root / "image_t2w.nii.gz",
        "image_t2f": input_root / "image_t2f.nii.gz",
    }
    for path in artifacts.values():
        path.write_bytes(b"cached")
    session = {
        "ok": True,
        "session_id": "brain-tumor-old-success",
        "status": "complete",
        "source": {
            "type": "remote_case_registry",
            "registry_id": "registry-test",
            "case_id": "case-1",
            "timepoint_id": "time2",
        },
        "service": {"model_id": "dataset802-unified-4class"},
        "qc": {"warnings": []},
        "volumes": [{"region": "enhancing_tumor", "volume_mm3": 10.0}],
        "artifacts": {key: str(value) for key, value in artifacts.items()},
    }
    (session_root / "session.json").write_text(json.dumps(session), encoding="utf-8")
    registry = {
        "id": "registry-test",
        "model_id": "dataset802-unified-4class",
        "cases": [
            {
                "id": "case-1",
                "title": "Case 1",
                "dataset": "local-test",
                "timepoints": [
                    {
                        "id": "time2",
                        "label": "Follow-up",
                        "modalities": {
                            "t1n": "/remote/t1n.nii.gz",
                            "t1c": "/remote/t1c.nii.gz",
                            "t2w": "/remote/t2w.nii.gz",
                            "t2f": "/remote/t2f.nii.gz",
                        },
                    }
                ],
            }
        ],
    }

    monkeypatch.setattr(brain_tumor_module, "_load_case_registry", lambda: registry)
    monkeypatch.setattr(
        brain_tumor_module,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "tumor_segmentation_model_id": "dataset802-unified-4class",
                "segmentation_tool_remote_host": "should-not-be-used",
                "brain_tumor_dicom_remote_host": "",
            },
        )(),
    )
    monkeypatch.setattr(
        brain_tumor_module,
        "_run_checked",
        lambda *_args, **_kwargs: pytest.fail("remote registry cache miss unexpectedly invoked ssh"),
    )
    store = BrainTumorDemoStore(asset_root=asset_root)

    payload = store.run_case_registry_case(case_id="case-1", timepoint_ids=["time2"])

    cached = payload["sessions"][0]
    assert cached["session_id"] == "brain-tumor-old-success"
    assert cached["service"]["cache"] == "local_hit"
    assert cached["qc"]["cache"] == "local_hit"
    assert cached["viewer_assets"]["segmentation_url"].endswith("/seg/seg.nii.gz")
    assert cached["viewer_assets"]["modality_volume_urls"]["t1c"].endswith("/image_t1c/image_t1c.nii.gz")

    store._registry_case_summary_cache_path.unlink()
    assert store.get_case_registry()["cases"][0]["demo_quality"]["cache_count"] == 0
    loaded = store.load_case_registry_case(case_id="case-1", prefer_cached=True)
    assert loaded["points"][0]["segmentationUrl"]
    assert loaded["points"][0]["groundTruthSegmentationUrl"].endswith("/ground_truth_seg/reference.nii.gz")
    assert store.get_case_registry()["cases"][0]["demo_quality"]["cache_count"] == 1


def test_brain_tumor_registry_cache_rebases_relocated_session_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "current"
    old_root = tmp_path / "old-release"
    registry_id = "registry-test"
    case_id = "case-relocated"
    timepoint_id = "time1"
    model_id = "dataset802-unified-4class"
    session_id = brain_tumor_module._registry_cache_session_id(
        registry_id=registry_id,
        case_id=case_id,
        timepoint_id=timepoint_id,
        model_id=model_id,
    )
    session_root = asset_root / session_id
    artifact_rel_paths = {
        "seg": Path("outputs/seg.nii.gz"),
        "tumor_regions": Path("outputs/tumor_regions.json"),
        "volumes_csv": Path("outputs/volumes.csv"),
        "overlay_preview": Path("outputs/overlay_preview.png"),
        "image_t1n": Path("input/nifti/image_t1n.nii.gz"),
        "image_t1c": Path("input/nifti/image_t1c.nii.gz"),
        "image_t2w": Path("input/nifti/image_t2w.nii.gz"),
        "image_t2f": Path("input/nifti/image_t2f.nii.gz"),
    }
    for relative_path in artifact_rel_paths.values():
        path = session_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"cached")
    session = {
        "ok": True,
        "session_id": session_id,
        "status": "complete",
        "source": {
            "type": "remote_case_registry",
            "registry_id": registry_id,
            "case_id": case_id,
            "timepoint_id": timepoint_id,
        },
        "service": {"model_id": model_id},
        "qc": {"warnings": []},
        "volumes": [{"region": "enhancing_tumor", "volume_mm3": 10.0}],
        "artifacts": {
            key: str(old_root / session_id / relative_path)
            for key, relative_path in artifact_rel_paths.items()
        },
    }
    (session_root / "session.json").write_text(json.dumps(session), encoding="utf-8")
    registry = {
        "id": registry_id,
        "model_id": model_id,
        "cases": [
            {
                "id": case_id,
                "title": "Relocated cache",
                "dataset": "local-test",
                "timepoints": [
                    {
                        "id": timepoint_id,
                        "label": "Baseline",
                        "modalities": {
                            "t1n": "/remote/t1n.nii.gz",
                            "t1c": "/remote/t1c.nii.gz",
                            "t2w": "/remote/t2w.nii.gz",
                            "t2f": "/remote/t2f.nii.gz",
                        },
                    }
                ],
            }
        ],
    }
    monkeypatch.setattr(brain_tumor_module, "_load_case_registry", lambda: registry)
    monkeypatch.setattr(
        brain_tumor_module,
        "load_settings",
        lambda: type(
            "Settings",
            (),
            {
                "tumor_segmentation_model_id": model_id,
                "segmentation_tool_remote_host": "should-not-be-used",
                "brain_tumor_dicom_remote_host": "",
            },
        )(),
    )
    monkeypatch.setattr(
        brain_tumor_module,
        "_run_checked",
        lambda *_args, **_kwargs: pytest.fail("relocated cache should not invoke remote segmentation"),
    )
    store = BrainTumorDemoStore(asset_root=asset_root)

    payload = store.run_case_registry_case(case_id=case_id, timepoint_ids=[timepoint_id])

    cached = payload["sessions"][0]
    assert cached["service"]["cache"] == "local_hit"
    assert cached["artifacts"]["seg"] == str((session_root / "outputs/seg.nii.gz").resolve())
    assert cached["artifacts"]["image_t1c"] == str((session_root / "input/nifti/image_t1c.nii.gz").resolve())
    assert store.get_artifact_path(session_id, "seg") == (session_root / "outputs/seg.nii.gz").resolve()


def test_brain_tumor_remote_copy_reuses_existing_local_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    local_path = tmp_path / "image_t1c.nii.gz"
    local_path.write_bytes(b"cached")
    monkeypatch.setattr(
        brain_tumor_module.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("existing local artifact should not be copied again"),
    )

    copied = brain_tumor_module._copy_remote_file(
        remote_host="remote",
        remote_path="/remote/image_t1c.nii.gz",
        local_path=local_path,
        required=True,
    )

    assert copied == str(local_path.resolve())


def test_brain_tumor_remote_copy_uses_scp_when_alias_host_path_is_not_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    local_path = tmp_path / "image_t1c.nii.gz"
    calls: list[list[str]] = []

    def fake_run(args: list[str], **_kwargs: object):
        calls.append(args)
        return type("Completed", (), {"returncode": 0, "stderr": "", "stdout": ""})()

    monkeypatch.setattr(brain_tumor_module.subprocess, "run", fake_run)

    copied = brain_tumor_module._copy_remote_file(
        remote_host="imaging-host",
        remote_path="/remote/image_t1c.nii.gz",
        local_path=local_path,
        required=True,
    )

    assert copied == str(local_path.resolve())
    assert calls == [["scp", "imaging-host:/remote/image_t1c.nii.gz", str(local_path)]]


def test_brain_tumor_gateway_upload_with_precomputed_segmentation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from clinagent.gateway import server as gateway_server
    from clinagent.platform import config as platform_config

    env_file = tmp_path / "gateway.env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLINAGENT_ENV_FILE", str(env_file))
    monkeypatch.setenv("CLINAGENT_AUTH_DB", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("CLINAGENT_DATABASE_PATH", str(tmp_path / "state.sqlite3"))
    monkeypatch.setenv("CLINAGENT_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("CLINAGENT_LOCAL_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setattr(platform_config, "_loaded", False)
    monkeypatch.setattr(platform_config, "_env_file", None)

    store = BrainTumorDemoStore(asset_root=tmp_path / "brain-tumor")
    monkeypatch.setattr(gateway_server, "_get_brain_tumor_demo_store", lambda: store)
    monkeypatch.setattr(gateway_server, "load_config", lambda: object())
    monkeypatch.setattr(gateway_server, "get_default_model", lambda _config: "gpt-5-mini")
    monkeypatch.setattr(gateway_server, "create_provider", lambda *_args, **_kwargs: object())

    t1n = _write_nifti(tmp_path / "case_t1n.nii.gz", np.ones((16, 16, 16), dtype=np.float32))
    t1c = _write_nifti(tmp_path / "case_t1c.nii.gz", np.ones((16, 16, 16), dtype=np.float32))
    t2w = _write_nifti(tmp_path / "case_t2w.nii.gz", np.ones((16, 16, 16), dtype=np.float32))
    t2f = _write_nifti(tmp_path / "case_t2f.nii.gz", np.ones((16, 16, 16), dtype=np.float32))
    seg_data = np.zeros((16, 16, 16), dtype=np.uint8)
    seg_data[4:8, 4:8, 4:8] = 2
    seg_data[6:8, 6:8, 6:8] = 3
    seg = _write_nifti(tmp_path / "seg.nii.gz", seg_data)

    app, _, _ = gateway_server.create_app()
    client = TestClient(app)
    with t1n.open("rb") as t1n_handle, t1c.open("rb") as t1c_handle, t2w.open("rb") as t2w_handle, t2f.open("rb") as t2f_handle, seg.open("rb") as seg_handle:
        response = client.post(
            "/api/demo/brain-tumor/analyze",
            data={"input_mode": "nifti_upload", "patient_label": "Case A", "modality_mapping_json": json.dumps({})},
            files={
                "t1n_file": ("t1n.nii.gz", t1n_handle, "application/gzip"),
                "t1c_file": ("t1c.nii.gz", t1c_handle, "application/gzip"),
                "t2w_file": ("t2w.nii.gz", t2w_handle, "application/gzip"),
                "t2f_file": ("t2f.nii.gz", t2f_handle, "application/gzip"),
                "precomputed_seg_file": ("seg.nii.gz", seg_handle, "application/gzip"),
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["modality_status"]["t1c"]["present"] is True
    assert payload["modality_status"]["t2f"]["present"] is True
    assert payload["report_snippet"]["findings"].startswith("Research tumor segmentation estimates")
    assert any(row["region"] == "whole_tumor" and row["volume_ml"] > 0 for row in payload["volumes"])
