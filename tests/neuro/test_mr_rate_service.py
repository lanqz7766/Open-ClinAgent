from __future__ import annotations

import csv
import json
import threading
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from clinagent.families.neuro.knowledge.mr_rate_service import (
    CatalogAPIHandler,
    DEFAULT_COHORT_SIZE,
    LocalThreadingHTTPServer,
    connect_db,
    ensure_root_layout,
    ingest_dataset,
    search_catalog,
)


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _write_zip(path: Path, members: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _make_source_root(tmp_path: Path) -> Path:
    source_root = tmp_path / "source"

    metadata_header = [
        "patient_uid",
        "study_uid",
        "series_id",
        "classified_modality",
        "is_derived",
        "acquisition_plane",
        "anon_study_date",
        "sequence_family",
        "Patient'sAge",
        "Patient'sSex",
    ]
    metadata_rows = [
        ["P1", "S1", "t1w-raw-axi", "T1w", "False", "AXIAL", "2024-01-01", "t1w", "031Y", "F"],
        ["P1", "S1", "t2w-raw-axi", "T2w", "False", "AXIAL", "2024-01-01", "t2w", "031Y", "F"],
        ["P2", "S2", "t1w-raw-axi", "T1w", "False", "AXIAL", "2023-06-01", "t1w", "054Y", "M"],
        ["P2", "S3", "flair-raw-axi", "FLAIR", "False", "AXIAL", "2024-06-01", "flair", "055Y", "M"],
        ["P3", "S4", "t1w-raw-sag", "T1w", "False", "SAGITTAL", "2024-02-10", "t1w", "067Y", "F"],
        ["P4", "S5", "t1w-raw-axi", "T1w", "False", "AXIAL", "2022-07-01", "t1w", "043Y", "M"],
        ["P4", "S6", "t1w-raw-axi", "T1w", "False", "AXIAL", "2023-07-01", "t1w", "044Y", "M"],
    ]
    _write_csv(source_root / "MR-RATE" / "metadata" / "batch00_metadata.csv", metadata_header, metadata_rows)

    report_header = ["study_uid", "report", "clinical_information", "technique", "findings", "impression"]
    report_rows = [
        ["S1", "Normal brain MRI.", "Headache", "T1/T2", "No abnormality noted.", "Within normal limits."],
        ["S2", "Brain MRI shows enhancing lesion.", "Seizure", "T1/FLAIR", "Enhancing mass in left frontal lobe.", "Abnormal enhancing lesion."],
        ["S3", "Follow-up MRI still shows lesion.", "Seizure", "T1/FLAIR", "Persistent lesion with edema.", "Abnormal follow-up."],
        ["S4", "Solitary lesion in temporal lobe.", "Confusion", "T1", "Temporal lobe lesion.", "Abnormal lesion."],
        ["S5", "Normal study.", "Dizziness", "T1", "No acute intracranial abnormality.", "Normal study."],
        ["S6", "Normal follow-up study.", "Dizziness", "T1", "No abnormality.", "Within normal limits."],
    ]
    _write_csv(source_root / "MR-RATE" / "reports" / "batch00_reports.csv", report_header, report_rows)

    for study_uid in ("S1", "S2", "S3", "S4", "S5", "S6"):
        _write_zip(
            source_root / "MR-RATE" / "mri" / "batch00" / f"{study_uid}.zip",
            {
                f"{study_uid}/img/{study_uid}_t1w-raw-axi.nii.gz": "image",
                f"{study_uid}/seg/{study_uid}_t1w-raw-axi_brain-mask.nii.gz": "mask",
            },
        )
        _write_zip(
            source_root / "MR-RATE-vista-seg" / "mri" / "batch00" / f"{study_uid}_vista-seg.zip",
            {
                f"{study_uid}/seg/{study_uid}_t1w-raw-axi_vista-seg.nii.gz": "vista",
            },
        )
        _write_zip(
            source_root / "MR-RATE-nvseg-ctmr" / "mri" / "batch00" / f"{study_uid}_nvseg-ctmr.zip",
            {
                f"{study_uid}/seg/{study_uid}_t1w-raw-axi_nvseg-ctmr-wb.nii.gz": "nvseg",
            },
        )

    return source_root


def test_ingest_dataset_builds_catalog_and_manifests(tmp_path: Path) -> None:
    source_root = _make_source_root(tmp_path)
    output_root = tmp_path / "knowledge"

    result = ingest_dataset(output_root, source_root, cohort_size=4)

    assert result["candidate_count"] == 4
    assert result["cohort_count"] == 4
    assert Path(result["candidate_manifest"]).exists()
    assert Path(result["cohort_manifest"]).exists()

    with connect_db(output_root / "catalog" / "mr_rate.sqlite") as conn:
        counts = {
            "cases": conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
            "studies": conn.execute("SELECT COUNT(*) FROM studies").fetchone()[0],
            "series": conn.execute("SELECT COUNT(*) FROM series").fetchone()[0],
            "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
        }
        assert counts == {"cases": 4, "studies": 6, "series": 7, "assets": 18}
        search_hits = search_catalog(conn, "lesion", limit=5)
        assert any(item["kind"] == "study" for item in search_hits)
        cohort_tag_count = conn.execute(
            "SELECT COUNT(*) FROM cases WHERE cohort_tag = 'mr_rate_cohort_v1_provisional'"
        ).fetchone()[0]
        assert cohort_tag_count == 4

    case_summary = json.loads((output_root / "summaries" / "cases" / "P2.json").read_text(encoding="utf-8"))
    assert case_summary["case_label"] == "abnormal"
    assert case_summary["patient_age"] == 54
    assert case_summary["patient_sex"] == "M"


def test_http_api_serves_health_and_search(tmp_path: Path) -> None:
    source_root = _make_source_root(tmp_path)
    output_root = tmp_path / "knowledge"
    ensure_root_layout(output_root, source_root)
    ingest_dataset(output_root, source_root, cohort_size=min(4, DEFAULT_COHORT_SIZE))

    CatalogAPIHandler.root_dir = output_root
    server = LocalThreadingHTTPServer(("127.0.0.1", 0), CatalogAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(f"{base}/health") as response:
            health = json.loads(response.read().decode("utf-8"))
        assert health["ok"] is True
        assert health["counts"]["cases"] == 4

        query = urllib.parse.quote("lesion")
        with urllib.request.urlopen(f"{base}/search?q={query}") as response:
            search = json.loads(response.read().decode("utf-8"))
        assert search["ok"] is True
        assert any(item["kind"] == "study" for item in search["results"])
    finally:
        server.shutdown()
        server.server_close()


def test_http_api_creates_analysis_launch_and_serves_files(tmp_path: Path) -> None:
    source_root = _make_source_root(tmp_path)
    output_root = tmp_path / "knowledge"
    ensure_root_layout(output_root, source_root)
    ingest_dataset(output_root, source_root, cohort_size=min(4, DEFAULT_COHORT_SIZE))

    CatalogAPIHandler.root_dir = output_root
    server = LocalThreadingHTTPServer(("127.0.0.1", 0), CatalogAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        request = urllib.request.Request(
            f"{base}/analysis-launches",
            data=json.dumps({"patient_uid": "P2", "study_uid": "S2"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            manifest = json.loads(response.read().decode("utf-8"))

        assert manifest["ok"] is True
        assert manifest["patient_uid"] == "P2"
        assert manifest["study_uid"] == "S2"
        assert manifest["has_segmentation"] is True
        assert manifest["knowledge_context"]["study"]["patient_age"] == 54
        assert manifest["knowledge_context"]["study"]["patient_sex"] == "M"

        launch_id = manifest["launch_id"]
        with urllib.request.urlopen(f"{base}/analysis-launches/{launch_id}/manifest") as response:
            fetched_manifest = json.loads(response.read().decode("utf-8"))
        assert fetched_manifest["launch_id"] == launch_id

        with urllib.request.urlopen(f"{base}/analysis-launches/{launch_id}/files/image") as response:
            image_bytes = response.read()
        with urllib.request.urlopen(f"{base}/analysis-launches/{launch_id}/files/seg") as response:
            seg_bytes = response.read()

        assert image_bytes == b"image"
        assert seg_bytes == b"vista"
    finally:
        server.shutdown()
        server.server_close()
