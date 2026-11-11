"""MR-RATE knowledge-layer ingest and read-only API service.

This module is intentionally self-contained so the same file can be copied to a
remote host and executed with the standard library only.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import textwrap
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse


DEFAULT_SOURCE_ROOT = Path(os.environ.get("CLINAGENT_MR_RATE_SOURCE_ROOT", "/tmp/clinagent-mr-rate-source"))
DEFAULT_OUTPUT_ROOT = Path(os.environ.get("CLINAGENT_MR_RATE_OUTPUT_ROOT", "/tmp/clinagent-mr-rate"))
DEFAULT_PORT = 18120
DEFAULT_COHORT_SIZE = 16
DEFAULT_BATCH_LIMIT = 1
COHORT_TAG = "mr_rate_cohort_v1_provisional"
INGEST_RULE_VERSION = "v1"


class LocalThreadingHTTPServer(ThreadingHTTPServer):
    """Threaded local HTTP server without a reverse-DNS lookup during bind."""

    daemon_threads = True

    def server_bind(self) -> None:
        TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)

NORMAL_PATTERNS = (
    "within normal limits",
    "within normal limit",
    "no abnormality",
    "no acute intracranial",
    "normal brain mri",
    "normal cranial mri",
    "unremarkable",
    "normal study",
    "normal examination",
)
ABNORMAL_PATTERNS = (
    "mass",
    "lesion",
    "tumor",
    "metast",
    "glioma",
    "hemorrhage",
    "haemorrhage",
    "infarct",
    "ischemia",
    "ischemic",
    "edema",
    "oedema",
    "abnormal signal",
    "enhancing",
    "restricted diffusion",
    "hydrocephalus",
    "atrophy",
    "microangiopathic",
    "aneurysm",
    "subdural",
    "epidural",
    "meningioma",
    "encephalomalacia",
)
PREFERRED_IMAGE_TOKENS = (
    "t1w-raw-sag",
    "t1w-raw-cor",
    "t1w-raw-axi",
    "t1w",
    "t2w",
    "flair",
)
MASK_MEMBER_SUFFIXES = (
    "_brain-mask.nii.gz",
    "_defacing-mask.nii.gz",
)


@dataclass(frozen=True)
class AssetRecord:
    patient_uid: str
    study_uid: Optional[str]
    asset_kind: str
    source_path: str
    batch_id: str
    member_count: int
    available: int
    segmentation_family: Optional[str] = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_root_layout(root: Path, source_root: Path, port: int = DEFAULT_PORT) -> dict[str, Path]:
    root = root.resolve()
    layout = {
        "root": root,
        "catalog": root / "catalog",
        "manifests": root / "manifests",
        "summaries": root / "summaries",
        "cases": root / "summaries" / "cases",
        "studies": root / "summaries" / "studies",
        "api": root / "api",
        "docs": root / "docs",
        "logs": root / "logs",
    }
    for path in layout.values():
        if path.suffix:
            continue
        path.mkdir(parents=True, exist_ok=True)
    _write_support_docs(layout, source_root=source_root, port=port)
    _write_support_scripts(layout, port=port)
    return layout


def _write_support_docs(layout: dict[str, Path], *, source_root: Path, port: int) -> None:
    docs = layout["docs"]
    readme = textwrap.dedent(
        f"""\
        # ClinAgent MR-RATE Knowledge Root

        This directory stores the first-pass MR-RATE knowledge layer.

        ## Layout

        - `catalog/` SQLite catalog, FTS index tables, ingest logs
        - `manifests/` candidate and cohort manifests
        - `summaries/` de-identified case and study summaries
        - `api/` read-only HTTP service and helper scripts
        - `logs/` service logs
        - `docs/` dataset and cohort notes

        ## Access

        The read-only API binds to `127.0.0.1:{port}` on the remote host.
        Access it from a trusted machine with:

        ```bash
        ssh -L {port}:127.0.0.1:{port} <ssh-host-alias>
        curl -fsS http://127.0.0.1:{port}/health
        ```
        """
    )
    mr_rate_doc = textwrap.dedent(
        f"""\
        # MR-RATE Dataset Notes

        ## Source

        - Root: `{source_root}`
        - Included in v1:
          - `MR-RATE/metadata/*.csv`
          - `MR-RATE/reports/*.csv`
          - `MR-RATE/mri/batch*/<patient>.zip`
          - `MR-RATE-vista-seg/mri/batch*/<patient>_*.zip`
          - `MR-RATE-nvseg-ctmr/mri/batch*/<patient>_*.zip`
        - Deferred to phase 2:
          - `MR-RATE-coreg`
          - `MR-RATE-atlas`

        ## Key Mapping

        - `patient_uid`: case-level identifier
        - `study_uid`: study/report identifier
        - `series_id`: series-level identifier, unique within `study_uid`

        ## PHI Boundary

        - The catalog only stores research identifiers, structured metadata,
          report text, summaries, and file paths.
        - No image payloads are copied.
        - No direct patient identifiers are exposed through the API.
        """
    )
    cohort_doc = textwrap.dedent(
        """\
        # Cohort V1

        This file is rewritten after each ingest.
        The current manifest lives at `../manifests/mr_rate_cohort_v1.jsonl`.

        Selection rules:

        - asset complete: metadata + report + MRI zip + vista + nvseg
        - mixed normal and abnormal cases
        - mixed single-study and multi-study cases
        - ranked by report richness

        Current status: provisional, pending manual review.
        """
    )
    (docs / "README.md").write_text(readme, encoding="utf-8")
    (docs / "MR-RATE.md").write_text(mr_rate_doc, encoding="utf-8")
    (docs / "COHORT_V1.md").write_text(cohort_doc, encoding="utf-8")


def _write_support_scripts(layout: dict[str, Path], *, port: int) -> None:
    api_dir = layout["api"]
    root = layout["root"]
    service_path = api_dir / "mr_rate_service.py"
    log_path = layout["logs"] / "mr_rate_api.log"
    session = "clinagent-mr-rate-api"

    start_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="{root}"
        PORT="${{CLINAGENT_MR_RATE_API_PORT:-{port}}}"
        SESSION="{session}"
        LOG="{log_path}"

        if tmux has-session -t "${{SESSION}}" >/dev/null 2>&1; then
          echo "MR-RATE API already running in tmux session '${{SESSION}}'."
          exit 0
        fi

        mkdir -p "$(dirname "${{LOG}}")"
        tmux new-session -d -s "${{SESSION}}" \
          "exec python3 '{service_path}' serve --root '{root}' --host 127.0.0.1 --port ${{PORT}} >>'${{LOG}}' 2>&1"
        echo "Started MR-RATE API on 127.0.0.1:${{PORT}} in tmux session '${{SESSION}}'."
        """
    )
    stop_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        SESSION="{session}"
        tmux kill-session -t "${{SESSION}}" >/dev/null 2>&1 || true
        echo "Stopped MR-RATE API session '${{SESSION}}'."
        """
    )
    status_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        PORT="${{CLINAGENT_MR_RATE_API_PORT:-{port}}}"
        curl -fsS "http://127.0.0.1:${{PORT}}/health"
        """
    )
    ingest_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        set -euo pipefail

        ROOT="{root}"
        SOURCE_ROOT="${{CLINAGENT_MR_RATE_SOURCE_ROOT:-}}"
        if [[ -z "${{SOURCE_ROOT}}" ]]; then
          echo "Set CLINAGENT_MR_RATE_SOURCE_ROOT before running the ingest helper." >&2
          exit 1
        fi
        python3 '{service_path}' ingest --root "$ROOT" --source-root "${{SOURCE_ROOT}}" --cohort-size {DEFAULT_COHORT_SIZE} --cohort-only --batch-limit {DEFAULT_BATCH_LIMIT}
        """
    )

    (api_dir / "start_api.sh").write_text(start_script, encoding="utf-8")
    (api_dir / "stop_api.sh").write_text(stop_script, encoding="utf-8")
    (api_dir / "status_api.sh").write_text(status_script, encoding="utf-8")
    (api_dir / "run_ingest.sh").write_text(ingest_script, encoding="utf-8")
    for name in ("start_api.sh", "stop_api.sh", "status_api.sh", "run_ingest.sh"):
        os.chmod(api_dir / name, 0o755)


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    existing = {
        str(row["name"])
        for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing:
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def initialize_catalog(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS cases (
            patient_uid TEXT PRIMARY KEY,
            study_count INTEGER NOT NULL DEFAULT 0,
            report_count INTEGER NOT NULL DEFAULT 0,
            has_mri_zip INTEGER NOT NULL DEFAULT 0,
            has_vista_seg INTEGER NOT NULL DEFAULT 0,
            has_nvseg INTEGER NOT NULL DEFAULT 0,
            cohort_tag TEXT,
            summary_path TEXT
        );

        CREATE TABLE IF NOT EXISTS studies (
            study_uid TEXT PRIMARY KEY,
            patient_uid TEXT NOT NULL,
            anon_study_date TEXT,
            patient_age INTEGER,
            patient_sex TEXT,
            report_available INTEGER NOT NULL DEFAULT 0,
            report_summary_path TEXT,
            FOREIGN KEY (patient_uid) REFERENCES cases(patient_uid)
        );

        CREATE TABLE IF NOT EXISTS series (
            study_uid TEXT NOT NULL,
            series_id TEXT NOT NULL,
            patient_uid TEXT NOT NULL,
            classified_modality TEXT,
            sequence_family TEXT,
            acquisition_plane TEXT,
            is_derived INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (study_uid, series_id),
            FOREIGN KEY (study_uid) REFERENCES studies(study_uid),
            FOREIGN KEY (patient_uid) REFERENCES cases(patient_uid)
        );

        CREATE TABLE IF NOT EXISTS assets (
            asset_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_uid TEXT NOT NULL,
            study_uid TEXT,
            asset_kind TEXT NOT NULL,
            source_path TEXT NOT NULL UNIQUE,
            batch_id TEXT,
            member_count INTEGER NOT NULL DEFAULT 0,
            available INTEGER NOT NULL DEFAULT 1,
            segmentation_family TEXT,
            FOREIGN KEY (patient_uid) REFERENCES cases(patient_uid),
            FOREIGN KEY (study_uid) REFERENCES studies(study_uid)
        );

        CREATE TABLE IF NOT EXISTS segmentation_members (
            member_id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL,
            member_path TEXT NOT NULL,
            sequence_token TEXT,
            segmentation_family TEXT NOT NULL,
            FOREIGN KEY (asset_id) REFERENCES assets(asset_id)
        );

        CREATE TABLE IF NOT EXISTS reports (
            study_uid TEXT PRIMARY KEY,
            clinical_information TEXT,
            technique TEXT,
            findings TEXT,
            impression TEXT,
            report_text TEXT,
            FOREIGN KEY (study_uid) REFERENCES studies(study_uid)
        );

        CREATE TABLE IF NOT EXISTS ingest_runs (
            ingest_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            data_source TEXT NOT NULL,
            rule_version TEXT NOT NULL,
            candidate_count INTEGER NOT NULL DEFAULT 0,
            cohort_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS case_search USING fts5(
            patient_uid UNINDEXED,
            summary
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS study_search USING fts5(
            study_uid UNINDEXED,
            patient_uid UNINDEXED,
            summary,
            findings,
            impression,
            report_text
        );
        """
    )
    _ensure_column(conn, "studies", "patient_age", "INTEGER")
    _ensure_column(conn, "studies", "patient_sex", "TEXT")
    conn.commit()


def reset_catalog(conn: sqlite3.Connection) -> None:
    for table in (
        "case_search",
        "study_search",
        "segmentation_members",
        "assets",
        "series",
        "reports",
        "studies",
        "cases",
    ):
        conn.execute(f"DELETE FROM {table}")
    conn.commit()


def iter_metadata_rows(source_root: Path, batch_limit: Optional[int] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = sorted((source_root / "MR-RATE" / "metadata").glob("batch*_metadata.csv"))
    if batch_limit is not None and batch_limit > 0:
        paths = paths[:batch_limit]
    for path in paths:
        batch_id = path.stem.replace("_metadata", "")
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["_batch_id"] = batch_id
                rows.append(row)
    return rows


def iter_report_rows(source_root: Path, batch_limit: Optional[int] = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths = sorted((source_root / "MR-RATE" / "reports").glob("batch*_reports.csv"))
    if batch_limit is not None and batch_limit > 0:
        paths = paths[:batch_limit]
    for path in paths:
        batch_id = path.stem.replace("_reports", "")
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                row["_batch_id"] = batch_id
                rows.append(row)
    return rows


def scan_assets(source_root: Path, study_patient: Dict[str, str]) -> List[AssetRecord]:
    roots = (
        ("mri_zip", None, source_root / "MR-RATE" / "mri", ".zip"),
        ("vista_zip", "vista", source_root / "MR-RATE-vista-seg" / "mri", "_vista-seg.zip"),
        ("nvseg_zip", "nvseg", source_root / "MR-RATE-nvseg-ctmr" / "mri", "_nvseg-ctmr.zip"),
    )
    assets: List[AssetRecord] = []
    for asset_kind, family, root, suffix in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob("batch*/*.zip")):
            if not path.name.endswith(suffix):
                continue
            study_uid = _study_uid_from_zip(path.name)
            patient_uid = study_patient.get(study_uid)
            if not patient_uid:
                continue
            assets.append(
                AssetRecord(
                    patient_uid=patient_uid,
                    study_uid=study_uid,
                    asset_kind=asset_kind,
                    source_path=str(path.resolve()),
                    batch_id=path.parent.name,
                    member_count=0,
                    available=1,
                    segmentation_family=family,
                )
            )
    return assets


def scan_assets_for_studies(source_root: Path, study_patient: Dict[str, str], study_uids: List[str]) -> List[AssetRecord]:
    assets: List[AssetRecord] = []
    for study_uid in study_uids:
        patient_uid = study_patient.get(study_uid)
        if not patient_uid:
            continue
        for path in sorted((source_root / "MR-RATE" / "mri").glob(f"batch*/{study_uid}.zip")):
            assets.append(
                AssetRecord(
                    patient_uid=patient_uid,
                    study_uid=study_uid,
                    asset_kind="mri_zip",
                    source_path=str(path.resolve()),
                    batch_id=path.parent.name,
                    member_count=0,
                    available=1,
                    segmentation_family=None,
                )
            )
        for path in sorted((source_root / "MR-RATE-vista-seg" / "mri").glob(f"batch*/{study_uid}_vista-seg.zip")):
            assets.append(
                AssetRecord(
                    patient_uid=patient_uid,
                    study_uid=study_uid,
                    asset_kind="vista_zip",
                    source_path=str(path.resolve()),
                    batch_id=path.parent.name,
                    member_count=0,
                    available=1,
                    segmentation_family="vista",
                )
            )
        for path in sorted((source_root / "MR-RATE-nvseg-ctmr" / "mri").glob(f"batch*/{study_uid}_nvseg-ctmr.zip")):
            assets.append(
                AssetRecord(
                    patient_uid=patient_uid,
                    study_uid=study_uid,
                    asset_kind="nvseg_zip",
                    source_path=str(path.resolve()),
                    batch_id=path.parent.name,
                    member_count=0,
                    available=1,
                    segmentation_family="nvseg",
                )
            )
    return assets


def build_asset_kind_index(source_root: Path, study_patient: Dict[str, str]) -> Dict[str, set[str]]:
    roots = (
        ("mri_zip", source_root / "MR-RATE" / "mri", ".zip"),
        ("vista_zip", source_root / "MR-RATE-vista-seg" / "mri", "_vista-seg.zip"),
        ("nvseg_zip", source_root / "MR-RATE-nvseg-ctmr" / "mri", "_nvseg-ctmr.zip"),
    )
    index: Dict[str, set[str]] = defaultdict(set)
    for asset_kind, root, suffix in roots:
        if not root.exists():
            continue
        for path in root.glob("batch*/*.zip"):
            if not path.name.endswith(suffix):
                continue
            study_uid = _study_uid_from_zip(path.name)
            patient_uid = study_patient.get(study_uid)
            if not patient_uid:
                continue
            index[patient_uid].add(asset_kind)
    return index


def _choose_cohort_seed_patients(
    *,
    metadata_rows: List[Dict[str, Any]],
    report_rows: List[Dict[str, Any]],
    source_root: Path,
    cohort_size: int,
    oversample_factor: int = 4,
) -> List[str]:
    patient_studies: Dict[str, set[str]] = defaultdict(set)
    study_patient: Dict[str, str] = {}
    reports_by_study: Dict[str, Dict[str, str]] = {}
    report_count_by_patient: Counter[str] = Counter()

    for row in metadata_rows:
        patient_uid = str(row.get("patient_uid") or "").strip()
        study_uid = str(row.get("study_uid") or "").strip()
        if not patient_uid or not study_uid:
            continue
        patient_studies[patient_uid].add(study_uid)
        study_patient.setdefault(study_uid, patient_uid)

    asset_kinds_by_patient = build_asset_kind_index(source_root, study_patient)

    for row in report_rows:
        study_uid = str(row.get("study_uid") or "").strip()
        patient_uid = study_patient.get(study_uid)
        if not patient_uid:
            continue
        reports_by_study[study_uid] = {
            "report_text": str(row.get("report") or ""),
            "findings": str(row.get("findings") or ""),
            "impression": str(row.get("impression") or ""),
        }
        report_count_by_patient[patient_uid] += 1

    pre_candidates: List[Dict[str, Any]] = []
    for patient_uid, studies in patient_studies.items():
        study_payloads = [reports_by_study.get(study_uid, {}) for study_uid in sorted(studies)]
        report_texts = [
            " ".join(
                [
                    payload.get("report_text", ""),
                    payload.get("findings", ""),
                    payload.get("impression", ""),
                ]
            ).strip()
            for payload in study_payloads
            if payload
        ]
        richness = sum(len(text.split()) for text in report_texts)
        if not report_texts or richness <= 0:
            continue
        pre_candidates.append(
            {
                "patient_uid": patient_uid,
                "study_count": len(studies),
                "report_count": int(report_count_by_patient.get(patient_uid, 0)),
                "has_mri_zip": False,
                "has_vista_seg": False,
                "has_nvseg": False,
                "case_label": classify_case(report_texts),
                "cohort_shape": "multi_study" if len(studies) > 1 else "single_study",
                "richness_score": richness,
                "study_uids": sorted(studies),
                "summary_text": "",
            }
        )
    pre_candidates.sort(key=lambda item: (-item["richness_score"], item["patient_uid"]))

    eligible: List[Dict[str, Any]] = []
    for candidate in pre_candidates:
        kinds = asset_kinds_by_patient.get(candidate["patient_uid"], set())
        if {"mri_zip", "vista_zip", "nvseg_zip"}.issubset(kinds):
            eligible.append(
                {
                    **candidate,
                    "has_mri_zip": True,
                    "has_vista_seg": True,
                    "has_nvseg": True,
                }
            )
        if len(eligible) >= max(cohort_size * oversample_factor, 32):
            break

    return [item["patient_uid"] for item in select_recommended_cohort(eligible, cohort_size=cohort_size)]


def _study_uid_from_zip(filename: str) -> str:
    name = filename[:-4] if filename.endswith(".zip") else filename
    for suffix in ("_vista-seg", "_nvseg-ctmr"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _parse_patient_age(value: Any) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_patient_sex(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper()
    if text.startswith("M"):
        return "M"
    if text.startswith("F"):
        return "F"
    return None


def _zip_members(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        return archive.namelist()


def _sequence_token_from_member(member_path: str) -> str:
    name = Path(member_path).name
    for suffix in (
        "_vista-seg.nii.gz",
        "_nvseg-ctmr-wb.nii.gz",
        "_nvseg-ctmr-brain.nii.gz",
        "_brain-mask.nii.gz",
        "_defacing-mask.nii.gz",
        ".nii.gz",
    ):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _is_mask_member(member_path: str) -> bool:
    return any(member_path.endswith(suffix) for suffix in MASK_MEMBER_SUFFIXES)


def _candidate_image_members(path: Path) -> list[str]:
    return [
        member
        for member in _zip_members(path)
        if member.endswith(".nii.gz")
        and not _is_mask_member(member)
        and "_vista-seg" not in member
        and "_nvseg-ctmr" not in member
    ]


def _select_image_member(mri_members: list[str], preferred_sequence_token: str | None) -> str:
    if not mri_members:
        raise FileNotFoundError("No MRI NIfTI members are available in the selected archive.")
    if preferred_sequence_token:
        for member in mri_members:
            if _sequence_token_from_member(member) == preferred_sequence_token:
                return member
    lowered = [(member, Path(member).name.lower()) for member in mri_members]
    for token in PREFERRED_IMAGE_TOKENS:
        for member, name in lowered:
            if token in name:
                return member
    return sorted(mri_members)[0]


def _extract_member_to_path(archive_path: Path, member_path: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open(member_path) as source, destination.open("wb") as target:
            target.write(source.read())


def _launch_root(root_dir: Path) -> Path:
    target = root_dir / "api" / "analysis-launches"
    target.mkdir(parents=True, exist_ok=True)
    return target


def classify_case(report_texts: list[str]) -> str:
    if not report_texts:
        return "unknown"
    labels = [classify_report(text) for text in report_texts if text.strip()]
    if not labels:
        return "unknown"
    if any(label == "abnormal" for label in labels):
        return "abnormal"
    if all(label == "normal" for label in labels):
        return "normal"
    return "mixed"


def classify_report(text: str) -> str:
    normalized = " ".join(text.lower().split())
    if not normalized:
        return "unknown"
    if any(pattern in normalized for pattern in NORMAL_PATTERNS):
        if not any(
            token in normalized
            for token in ("mass", "lesion", "tumor", "metast", "hemorrhage", "infarct", "aneurysm")
        ):
            return "normal"
    if any(pattern in normalized for pattern in ABNORMAL_PATTERNS):
        return "abnormal"
    return "unknown"


def build_case_summary(*, patient_uid: str, study_rows: list[sqlite3.Row], report_rows: list[sqlite3.Row], assets: list[sqlite3.Row]) -> dict[str, Any]:
    dates = [row["anon_study_date"] for row in study_rows if row["anon_study_date"]]
    ages = [int(row["patient_age"]) for row in study_rows if row["patient_age"] is not None]
    sexes = [str(row["patient_sex"]) for row in study_rows if row["patient_sex"]]
    case_label = classify_case([row["report_text"] or "" for row in report_rows])
    text = (
        f"MR-RATE case {patient_uid} has {len(study_rows)} studies and {len(report_rows)} reports. "
        f"Asset availability: MRI zip={any(a['asset_kind']=='mri_zip' for a in assets)}, "
        f"vista={any(a['asset_kind']=='vista_zip' for a in assets)}, "
        f"nvseg={any(a['asset_kind']=='nvseg_zip' for a in assets)}. "
        f"Report label: {case_label}. "
        f"Study dates: {', '.join(sorted(set(dates))[:5]) or 'unknown'}."
    )
    return {
        "patient_uid": patient_uid,
        "study_count": len(study_rows),
        "report_count": len(report_rows),
        "patient_age": ages[0] if ages else None,
        "patient_sex": sexes[0] if sexes else None,
        "case_label": case_label,
        "study_dates": sorted(set(dates)),
        "summary_text": text,
    }


def build_study_summary(*, patient_uid: str, study_row: sqlite3.Row, report_row: Optional[sqlite3.Row], series_rows: List[sqlite3.Row]) -> dict[str, Any]:
    report_text = (report_row["report_text"] if report_row else "") or ""
    impression = (report_row["impression"] if report_row else "") or ""
    findings = (report_row["findings"] if report_row else "") or ""
    modalities = sorted({row["classified_modality"] for row in series_rows if row["classified_modality"]})
    label = classify_report(report_text)
    summary_text = (
        f"Study {study_row['study_uid']} for patient {patient_uid} on {study_row['anon_study_date'] or 'unknown date'}. "
        f"Series count: {len(series_rows)}. Modalities: {', '.join(modalities) or 'unknown'}. "
        f"Report label: {label}. Impression: {impression or 'none'} Findings: {findings or 'none'}"
    )
    return {
        "patient_uid": patient_uid,
        "study_uid": study_row["study_uid"],
        "anon_study_date": study_row["anon_study_date"],
        "patient_age": study_row["patient_age"],
        "patient_sex": study_row["patient_sex"],
        "report_label": label,
        "modalities": modalities,
        "summary_text": summary_text,
    }


def ingest_dataset(
    root: Path,
    source_root: Path,
    cohort_size: int = DEFAULT_COHORT_SIZE,
    cohort_only: bool = False,
    batch_limit: Optional[int] = None,
) -> dict[str, Any]:
    layout = ensure_root_layout(root, source_root)
    db_path = layout["catalog"] / "mr_rate.sqlite"
    conn = connect_db(db_path)
    initialize_catalog(conn)
    reset_catalog(conn)

    started_at = utc_now()
    conn.execute(
        "INSERT INTO ingest_runs (started_at, data_source, rule_version, status) VALUES (?, ?, ?, ?)",
        (started_at, str(source_root.resolve()), INGEST_RULE_VERSION, "running"),
    )
    ingest_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    metadata_rows = iter_metadata_rows(source_root, batch_limit=batch_limit)
    report_rows = iter_report_rows(source_root, batch_limit=batch_limit)
    selected_patient_uids: Optional[List[str]] = None
    if cohort_only:
        selected_patient_uids = _choose_cohort_seed_patients(
            metadata_rows=metadata_rows,
            report_rows=report_rows,
            source_root=source_root,
            cohort_size=cohort_size,
        )
        selected_patient_set = set(selected_patient_uids)
        metadata_rows = [row for row in metadata_rows if str(row.get("patient_uid") or "").strip() in selected_patient_set]
        selected_study_uids = {
            str(item.get("study_uid") or "").strip()
            for item in metadata_rows
            if str(item.get("study_uid") or "").strip()
        }
        report_rows = [
            row for row in report_rows
            if str(row.get("study_uid") or "").strip() in selected_study_uids
        ]

    patient_studies: dict[str, set[str]] = defaultdict(set)
    study_patient: dict[str, str] = {}
    study_dates: dict[str, str] = {}
    study_age: dict[str, int] = {}
    study_sex: dict[str, str] = {}
    study_series: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)

    for row in metadata_rows:
        patient_uid = str(row.get("patient_uid") or "").strip()
        study_uid = str(row.get("study_uid") or "").strip()
        series_id = str(row.get("series_id") or "").strip()
        if not patient_uid or not study_uid or not series_id:
            continue
        patient_studies[patient_uid].add(study_uid)
        study_patient.setdefault(study_uid, patient_uid)
        if row.get("anon_study_date"):
            study_dates.setdefault(study_uid, str(row["anon_study_date"]))
        parsed_age = _parse_patient_age(row.get("Patient'sAge"))
        if parsed_age is not None:
            study_age.setdefault(study_uid, parsed_age)
        parsed_sex = _parse_patient_sex(row.get("Patient'sSex"))
        if parsed_sex:
            study_sex.setdefault(study_uid, parsed_sex)
        study_series[study_uid].append(
            (
                series_id,
                str(row.get("classified_modality") or ""),
                str(row.get("sequence_family") or ""),
                1 if str(row.get("is_derived") or "").lower() == "true" else 0,
            )
        )

    if cohort_only:
        assets = scan_assets_for_studies(source_root, study_patient, sorted(study_patient))
    else:
        assets = scan_assets(source_root, study_patient)

    reports_by_study: dict[str, dict[str, str]] = {}
    report_count_by_patient: Counter[str] = Counter()
    for row in report_rows:
        study_uid = str(row.get("study_uid") or "").strip()
        if not study_uid or study_uid not in study_patient:
            continue
        reports_by_study[study_uid] = {
            "clinical_information": str(row.get("clinical_information") or ""),
            "technique": str(row.get("technique") or ""),
            "findings": str(row.get("findings") or ""),
            "impression": str(row.get("impression") or ""),
            "report_text": str(row.get("report") or ""),
        }
        report_count_by_patient[study_patient[study_uid]] += 1

    asset_flags: dict[str, set[str]] = defaultdict(set)
    for asset in assets:
        asset_flags[asset.patient_uid].add(asset.asset_kind)

    case_rows = []
    for patient_uid, studies in patient_studies.items():
        kinds = asset_flags.get(patient_uid, set())
        case_rows.append(
            (
                patient_uid,
                len(studies),
                int(report_count_by_patient.get(patient_uid, 0)),
                1 if "mri_zip" in kinds else 0,
                1 if "vista_zip" in kinds else 0,
                1 if "nvseg_zip" in kinds else 0,
                None,
                None,
            )
        )
    conn.executemany(
        """
        INSERT INTO cases (
            patient_uid, study_count, report_count, has_mri_zip,
            has_vista_seg, has_nvseg, cohort_tag, summary_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        case_rows,
    )

    study_rows = []
    for study_uid, patient_uid in study_patient.items():
        study_rows.append(
            (
                study_uid,
                patient_uid,
                study_dates.get(study_uid, ""),
                study_age.get(study_uid),
                study_sex.get(study_uid),
                1 if study_uid in reports_by_study else 0,
                None,
            )
        )
    conn.executemany(
        """
        INSERT INTO studies (
            study_uid, patient_uid, anon_study_date, patient_age, patient_sex, report_available, report_summary_path
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        study_rows,
    )

    series_rows = []
    for study_uid, entries in study_series.items():
        patient_uid = study_patient[study_uid]
        seen_series: set[str] = set()
        for series_id, modality, sequence_family, is_derived in entries:
            if series_id in seen_series:
                continue
            seen_series.add(series_id)
            acquisition_plane = _plane_from_series_id(series_id)
            series_rows.append(
                (
                    study_uid,
                    series_id,
                    patient_uid,
                    modality,
                    sequence_family,
                    acquisition_plane,
                    is_derived,
                )
            )
    conn.executemany(
        """
        INSERT INTO series (
            study_uid, series_id, patient_uid, classified_modality,
            sequence_family, acquisition_plane, is_derived
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        series_rows,
    )

    conn.executemany(
        """
        INSERT INTO reports (
            study_uid, clinical_information, technique, findings, impression, report_text
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                study_uid,
                payload["clinical_information"],
                payload["technique"],
                payload["findings"],
                payload["impression"],
                payload["report_text"],
            )
            for study_uid, payload in reports_by_study.items()
        ],
    )

    asset_id_by_path: dict[str, int] = {}
    for asset in assets:
        conn.execute(
            """
            INSERT INTO assets (
                patient_uid, study_uid, asset_kind, source_path, batch_id,
                member_count, available, segmentation_family
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset.patient_uid,
                asset.study_uid,
                asset.asset_kind,
                asset.source_path,
                asset.batch_id,
                asset.member_count,
                asset.available,
                asset.segmentation_family,
            ),
        )
        asset_id_by_path[asset.source_path] = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

    _write_summaries_and_fts(conn, layout)
    candidates, cohort = _write_manifests(conn, layout, cohort_size=cohort_size)

    cohort_patients = [entry["patient_uid"] for entry in cohort]
    conn.executemany(
        "UPDATE cases SET cohort_tag = ? WHERE patient_uid = ?",
        [(COHORT_TAG, patient_uid) for patient_uid in cohort_patients],
    )
    _enrich_selected_assets(conn, selected_patients=set(cohort_patients))
    conn.commit()

    completed_at = utc_now()
    conn.execute(
        """
        UPDATE ingest_runs
        SET completed_at = ?, candidate_count = ?, cohort_count = ?, status = ?
        WHERE ingest_id = ?
        """,
        (completed_at, len(candidates), len(cohort), "completed", ingest_id),
    )
    conn.commit()

    run_record = {
        "ingest_id": ingest_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "data_source": str(source_root.resolve()),
        "rule_version": INGEST_RULE_VERSION,
        "candidate_count": len(candidates),
        "cohort_count": len(cohort),
        "status": "completed",
    }
    with (layout["catalog"] / "ingest_runs.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(run_record, ensure_ascii=True) + "\n")

    conn.close()
    return {
        "db_path": str(db_path),
        "candidate_manifest": str((layout["manifests"] / "mr_rate_candidates.jsonl").resolve()),
        "cohort_manifest": str((layout["manifests"] / "mr_rate_cohort_v1.jsonl").resolve()),
        "candidate_count": len(candidates),
        "cohort_count": len(cohort),
    }


def _enrich_selected_assets(conn: sqlite3.Connection, *, selected_patients: set[str]) -> None:
    if not selected_patients:
        return
    placeholders = ",".join("?" for _ in selected_patients)
    asset_rows = conn.execute(
        f"""
        SELECT asset_id, source_path, segmentation_family
        FROM assets
        WHERE patient_uid IN ({placeholders})
        ORDER BY asset_id
        """,
        tuple(sorted(selected_patients)),
    ).fetchall()
    conn.execute(
        f"""
        DELETE FROM segmentation_members
        WHERE asset_id IN (
            SELECT asset_id FROM assets WHERE patient_uid IN ({placeholders})
        )
        """,
        tuple(sorted(selected_patients)),
    )
    for row in asset_rows:
        members = _zip_members(Path(row["source_path"]))
        conn.execute(
            "UPDATE assets SET member_count = ? WHERE asset_id = ?",
            (len(members), row["asset_id"]),
        )
        if row["segmentation_family"]:
            conn.executemany(
                """
                INSERT INTO segmentation_members (asset_id, member_path, sequence_token, segmentation_family)
                VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        row["asset_id"],
                        member,
                        _sequence_token_from_member(member),
                        row["segmentation_family"],
                    )
                    for member in members
                    if member.endswith(".nii.gz")
                ],
            )


def _plane_from_series_id(series_id: str) -> str:
    lowered = series_id.lower()
    if lowered.endswith("axi") or "-axi" in lowered:
        return "AXIAL"
    if lowered.endswith("cor") or "-cor" in lowered:
        return "CORONAL"
    if lowered.endswith("sag") or "-sag" in lowered:
        return "SAGITTAL"
    return ""


def _write_summaries_and_fts(conn: sqlite3.Connection, layout: dict[str, Path]) -> None:
    conn.execute("DELETE FROM case_search")
    conn.execute("DELETE FROM study_search")

    case_dir = layout["cases"]
    study_dir = layout["studies"]
    for path in case_dir.glob("*.json"):
        path.unlink()
    for path in study_dir.glob("*.json"):
        path.unlink()

    case_rows = conn.execute("SELECT * FROM cases ORDER BY patient_uid").fetchall()
    for case_row in case_rows:
        patient_uid = case_row["patient_uid"]
        studies = conn.execute(
            "SELECT * FROM studies WHERE patient_uid = ? ORDER BY anon_study_date, study_uid",
            (patient_uid,),
        ).fetchall()
        reports = conn.execute(
            """
            SELECT reports.* FROM reports
            JOIN studies ON studies.study_uid = reports.study_uid
            WHERE studies.patient_uid = ?
            ORDER BY studies.anon_study_date, reports.study_uid
            """,
            (patient_uid,),
        ).fetchall()
        assets = conn.execute(
            "SELECT * FROM assets WHERE patient_uid = ? ORDER BY asset_kind, source_path",
            (patient_uid,),
        ).fetchall()
        payload = build_case_summary(
            patient_uid=patient_uid,
            study_rows=studies,
            report_rows=reports,
            assets=assets,
        )
        path = case_dir / f"{patient_uid}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        conn.execute("UPDATE cases SET summary_path = ? WHERE patient_uid = ?", (str(path.resolve()), patient_uid))
        conn.execute(
            "INSERT INTO case_search (patient_uid, summary) VALUES (?, ?)",
            (patient_uid, payload["summary_text"]),
        )

    study_rows = conn.execute("SELECT * FROM studies ORDER BY anon_study_date, study_uid").fetchall()
    for study_row in study_rows:
        patient_uid = study_row["patient_uid"]
        report_row = conn.execute("SELECT * FROM reports WHERE study_uid = ?", (study_row["study_uid"],)).fetchone()
        series_rows = conn.execute(
            "SELECT * FROM series WHERE study_uid = ? ORDER BY series_id",
            (study_row["study_uid"],),
        ).fetchall()
        payload = build_study_summary(
            patient_uid=patient_uid,
            study_row=study_row,
            report_row=report_row,
            series_rows=series_rows,
        )
        path = study_dir / f"{study_row['study_uid']}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        conn.execute(
            "UPDATE studies SET report_summary_path = ? WHERE study_uid = ?",
            (str(path.resolve()), study_row["study_uid"]),
        )
        conn.execute(
            """
            INSERT INTO study_search (study_uid, patient_uid, summary, findings, impression, report_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                study_row["study_uid"],
                patient_uid,
                payload["summary_text"],
                (report_row["findings"] if report_row else "") or "",
                (report_row["impression"] if report_row else "") or "",
                (report_row["report_text"] if report_row else "") or "",
            ),
        )
    conn.commit()


def _write_manifests(conn: sqlite3.Connection, layout: Dict[str, Path], *, cohort_size: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    candidates = build_candidates(conn)
    cohort = select_recommended_cohort(candidates, cohort_size=cohort_size)
    candidates_path = layout["manifests"] / "mr_rate_candidates.jsonl"
    cohort_path = layout["manifests"] / "mr_rate_cohort_v1.jsonl"
    with candidates_path.open("w", encoding="utf-8") as handle:
        for item in candidates:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    with cohort_path.open("w", encoding="utf-8") as handle:
        for item in cohort:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
    _rewrite_cohort_doc(layout["docs"] / "COHORT_V1.md", cohort)
    return candidates, cohort


def build_candidates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    case_rows = conn.execute("SELECT * FROM cases ORDER BY patient_uid").fetchall()
    for row in case_rows:
        if not (row["has_mri_zip"] and row["has_vista_seg"] and row["has_nvseg"]):
            continue
        study_rows = conn.execute(
            """
            SELECT studies.*, reports.report_text, reports.impression, reports.findings
            FROM studies
            LEFT JOIN reports ON reports.study_uid = studies.study_uid
            WHERE studies.patient_uid = ?
            ORDER BY studies.anon_study_date, studies.study_uid
            """,
            (row["patient_uid"],),
        ).fetchall()
        report_texts = [((item["report_text"] or "") + " " + (item["impression"] or "")) for item in study_rows]
        richness = sum(len(text.split()) for text in report_texts)
        if richness <= 0:
            continue
        case_label = classify_case(report_texts)
        summary_payload = _read_json_if_exists(row["summary_path"])
        candidates.append(
            {
                "patient_uid": row["patient_uid"],
                "study_count": int(row["study_count"]),
                "report_count": int(row["report_count"]),
                "has_mri_zip": bool(row["has_mri_zip"]),
                "has_vista_seg": bool(row["has_vista_seg"]),
                "has_nvseg": bool(row["has_nvseg"]),
                "case_label": case_label,
                "cohort_shape": "multi_study" if int(row["study_count"]) > 1 else "single_study",
                "richness_score": richness,
                "study_uids": [item["study_uid"] for item in study_rows],
                "summary_text": (summary_payload or {}).get("summary_text", ""),
            }
        )
    candidates.sort(key=lambda item: (-item["richness_score"], item["patient_uid"]))
    return candidates


def select_recommended_cohort(candidates: list[dict[str, Any]], *, cohort_size: int) -> list[dict[str, Any]]:
    target_size = max(10, min(cohort_size, 20))
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in candidates:
        groups[(item["cohort_shape"], item["case_label"])].append(item)

    selected: list[dict[str, Any]] = []
    taken: set[str] = set()
    desired_order = (
        ("single_study", "abnormal", 4),
        ("single_study", "normal", 4),
        ("multi_study", "abnormal", 4),
        ("multi_study", "normal", 4),
    )
    for shape, label, quota in desired_order:
        for item in groups.get((shape, label), [])[:quota]:
            if item["patient_uid"] in taken:
                continue
            taken.add(item["patient_uid"])
            selected.append(item)
            if len(selected) >= target_size:
                break
        if len(selected) >= target_size:
            break

    if len(selected) < target_size:
        for item in candidates:
            if item["patient_uid"] in taken:
                continue
            taken.add(item["patient_uid"])
            selected.append(item)
            if len(selected) >= target_size:
                break

    cohort: list[dict[str, Any]] = []
    for index, item in enumerate(selected, start=1):
        cohort.append(
            {
                **item,
                "cohort_tag": COHORT_TAG,
                "cohort_rank": index,
                "selection_status": "provisional",
                "selection_reason": (
                    f"{item['cohort_shape']} + {item['case_label']} with richness score {item['richness_score']}"
                ),
            }
        )
    return cohort


def _read_json_if_exists(path_value: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _rewrite_cohort_doc(path: Path, cohort: list[dict[str, Any]]) -> None:
    lines = [
        "# Cohort V1",
        "",
        "Current status: provisional, pending manual review.",
        "",
        f"Selected cases: {len(cohort)}",
        "",
        "| Rank | patient_uid | Shape | Label | Richness |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in cohort:
        lines.append(
            f"| {item['cohort_rank']} | {item['patient_uid']} | {item['cohort_shape']} | {item['case_label']} | {item['richness_score']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def search_catalog(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    normalized = " ".join(part.strip() for part in query.split() if part.strip())
    if not normalized:
        return []
    terms = " ".join(normalized.split())
    results: list[dict[str, Any]] = []
    try:
        case_rows = conn.execute(
            """
            SELECT patient_uid, summary, bm25(case_search) AS rank
            FROM case_search
            WHERE case_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (terms, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        case_rows = conn.execute(
            "SELECT patient_uid, summary, 0 AS rank FROM case_search WHERE summary LIKE ? LIMIT ?",
            (f"%{normalized}%", limit),
        ).fetchall()
    for row in case_rows:
        results.append(
            {
                "kind": "case",
                "patient_uid": row["patient_uid"],
                "score": row["rank"],
                "snippet": row["summary"][:320],
            }
        )

    try:
        study_rows = conn.execute(
            """
            SELECT study_uid, patient_uid, summary, impression, bm25(study_search) AS rank
            FROM study_search
            WHERE study_search MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (terms, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        study_rows = conn.execute(
            """
            SELECT study_uid, patient_uid, summary, impression, 0 AS rank
            FROM study_search
            WHERE summary LIKE ? OR findings LIKE ? OR impression LIKE ? OR report_text LIKE ?
            LIMIT ?
            """,
            (f"%{normalized}%", f"%{normalized}%", f"%{normalized}%", f"%{normalized}%", limit),
        ).fetchall()
    for row in study_rows:
        results.append(
            {
                "kind": "study",
                "study_uid": row["study_uid"],
                "patient_uid": row["patient_uid"],
                "score": row["rank"],
                "snippet": (row["impression"] or row["summary"])[:320],
            }
        )
    results.sort(key=lambda item: (item.get("score", 0), item["kind"]))
    return results[:limit]


def _select_segmentation_member(
    conn: sqlite3.Connection,
    study_uid: str,
    segmentation_preference: str,
) -> dict[str, Any] | None:
    del segmentation_preference  # v1 uses a fixed priority order.
    asset_rows = conn.execute(
        """
        SELECT asset_id, asset_kind, source_path, segmentation_family
        FROM assets
        WHERE study_uid = ? AND asset_kind IN ('vista_zip', 'nvseg_zip')
        ORDER BY CASE asset_kind
            WHEN 'vista_zip' THEN 0
            WHEN 'nvseg_zip' THEN 1
            ELSE 9
        END, asset_id
        """,
        (study_uid,),
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    for asset_row in asset_rows:
        members = conn.execute(
            """
            SELECT member_path, sequence_token, segmentation_family
            FROM segmentation_members
            WHERE asset_id = ?
            ORDER BY member_path
            """,
            (asset_row["asset_id"],),
        ).fetchall()
        for member in members:
            member_path = member["member_path"]
            rank = 99
            if asset_row["asset_kind"] == "vista_zip":
                rank = 0
            elif member_path.endswith("_nvseg-ctmr-brain.nii.gz"):
                rank = 1
            elif member_path.endswith("_nvseg-ctmr-wb.nii.gz"):
                rank = 2
            candidates.append(
                {
                    "rank": rank,
                    "asset_kind": asset_row["asset_kind"],
                    "source_path": asset_row["source_path"],
                    "member_path": member_path,
                    "sequence_token": member["sequence_token"],
                    "segmentation_family": member["segmentation_family"],
                }
            )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["rank"], item["member_path"]))
    best = candidates[0].copy()
    best.pop("rank", None)
    return best


def _build_analysis_launch_payload(
    *,
    root_dir: Path,
    patient_uid: str,
    study_uid: str,
    segmentation_preference: str,
    sequence_preference: str,
) -> dict[str, Any]:
    del sequence_preference  # v1 uses the fixed structural sequence ranking.
    with connect_db(root_dir / "catalog" / "mr_rate.sqlite") as conn:
        case_row = conn.execute("SELECT * FROM cases WHERE patient_uid = ?", (patient_uid,)).fetchone()
        study_row = conn.execute("SELECT * FROM studies WHERE study_uid = ?", (study_uid,)).fetchone()
        if case_row is None:
            raise KeyError(f"Unknown patient_uid: {patient_uid}")
        if study_row is None or study_row["patient_uid"] != patient_uid:
            raise KeyError(f"Unknown study_uid for patient {patient_uid}: {study_uid}")
        case_data = dict(case_row)
        study_data = dict(study_row)
        summary = _read_json_if_exists(case_data["summary_path"])
        study_summary = _read_json_if_exists(study_data["report_summary_path"])
        report_row = conn.execute("SELECT * FROM reports WHERE study_uid = ?", (study_uid,)).fetchone()
        mri_asset = conn.execute(
            "SELECT * FROM assets WHERE study_uid = ? AND asset_kind = 'mri_zip' LIMIT 1",
            (study_uid,),
        ).fetchone()
        if mri_asset is None:
            raise FileNotFoundError(f"No MRI asset is indexed for study_uid {study_uid}")
        mri_asset_data = dict(mri_asset)
        segmentation = _select_segmentation_member(conn, study_uid, segmentation_preference)

    mri_archive = Path(mri_asset_data["source_path"])
    image_member = _select_image_member(
        _candidate_image_members(mri_archive),
        segmentation.get("sequence_token") if segmentation else None,
    )

    launch_id = uuid.uuid4().hex
    launch_dir = _launch_root(root_dir) / launch_id
    launch_dir.mkdir(parents=True, exist_ok=True)
    image_path = launch_dir / "image.nii.gz"
    _extract_member_to_path(mri_archive, image_member, image_path)

    seg_path: Path | None = None
    if segmentation:
        seg_path = launch_dir / "segmentation.nii.gz"
        _extract_member_to_path(Path(str(segmentation["source_path"])), str(segmentation["member_path"]), seg_path)

    knowledge_context = {
        "case": case_data,
        "study": study_data,
        "case_summary": summary,
        "study_summary": study_summary,
        "report": dict(report_row) if report_row else None,
    }
    manifest = {
        "ok": True,
        "launch_id": launch_id,
        "patient_uid": patient_uid,
        "study_uid": study_uid,
        "image": {
            "source_path": str(mri_archive),
            "member_path": image_member,
            "sequence_token": _sequence_token_from_member(image_member),
        },
        "segmentation": segmentation,
        "has_segmentation": seg_path is not None,
        "knowledge_context": knowledge_context,
    }
    (launch_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


class CatalogAPIHandler(BaseHTTPRequestHandler):
    root_dir: Path = DEFAULT_OUTPUT_ROOT

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path == "/health":
                self._send_json(self._health_payload())
                return
            if path.startswith("/analysis-launches/") and path.endswith("/manifest"):
                launch_id = path.split("/")[2]
                self._send_json(self._analysis_launch_manifest_payload(launch_id))
                return
            if path.startswith("/analysis-launches/") and "/files/" in path:
                parts = path.split("/")
                launch_id = parts[2]
                file_kind = parts[4]
                self._send_file(self._analysis_launch_file_path(launch_id, file_kind))
                return
            if path.startswith("/cases/") and path.endswith("/assets"):
                patient_uid = path.split("/")[2]
                self._send_json(self._case_assets_payload(patient_uid))
                return
            if path.startswith("/cases/"):
                patient_uid = path.split("/")[2]
                self._send_json(self._case_payload(patient_uid))
                return
            if path.startswith("/studies/"):
                study_uid = path.split("/")[2]
                self._send_json(self._study_payload(study_uid))
                return
            if path == "/search":
                terms = (query.get("q") or [""])[0]
                limit = int((query.get("limit") or ["10"])[0])
                with connect_db(self.root_dir / "catalog" / "mr_rate.sqlite") as conn:
                    self._send_json({"ok": True, "results": search_catalog(conn, terms, limit=limit)})
                return
            if path == "/cohorts/v1":
                self._send_json({"ok": True, "cohort": self._read_manifest("mr_rate_cohort_v1.jsonl")})
                return
            self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pragma: no cover - defensive path for live service
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/analysis-launches":
                payload = self._read_json_body()
                patient_uid = str(payload.get("patient_uid") or "").strip()
                study_uid = str(payload.get("study_uid") or "").strip()
                if not patient_uid or not study_uid:
                    self._send_json(
                        {"ok": False, "error": "patient_uid and study_uid are required"},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                    return
                segmentation_preference = str(payload.get("segmentation_preference") or "vista_then_nvseg").strip()
                sequence_preference = str(payload.get("sequence_preference") or "structural_default").strip()
                manifest = _build_analysis_launch_payload(
                    root_dir=self.root_dir,
                    patient_uid=patient_uid,
                    study_uid=study_uid,
                    segmentation_preference=segmentation_preference,
                    sequence_preference=sequence_preference,
                )
                self._send_json(manifest)
                return
            self._send_json({"ok": False, "error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:  # pragma: no cover - defensive path for live service
            self._send_json({"ok": False, "error": str(exc)}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _health_payload(self) -> dict[str, Any]:
        with connect_db(self.root_dir / "catalog" / "mr_rate.sqlite") as conn:
            counts = {
                "cases": conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0],
                "studies": conn.execute("SELECT COUNT(*) FROM studies").fetchone()[0],
                "series": conn.execute("SELECT COUNT(*) FROM series").fetchone()[0],
                "assets": conn.execute("SELECT COUNT(*) FROM assets").fetchone()[0],
            }
        return {"ok": True, "root": str(self.root_dir), "counts": counts}

    def _case_payload(self, patient_uid: str) -> dict[str, Any]:
        with connect_db(self.root_dir / "catalog" / "mr_rate.sqlite") as conn:
            case_row = conn.execute("SELECT * FROM cases WHERE patient_uid = ?", (patient_uid,)).fetchone()
            if case_row is None:
                raise KeyError(f"Unknown patient_uid: {patient_uid}")
            studies = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM studies WHERE patient_uid = ? ORDER BY anon_study_date, study_uid",
                    (patient_uid,),
                ).fetchall()
            ]
            summary = _read_json_if_exists(case_row["summary_path"])
        return {"ok": True, "case": dict(case_row), "summary": summary, "studies": studies}

    def _case_assets_payload(self, patient_uid: str) -> dict[str, Any]:
        with connect_db(self.root_dir / "catalog" / "mr_rate.sqlite") as conn:
            asset_rows = conn.execute(
                "SELECT * FROM assets WHERE patient_uid = ? ORDER BY asset_kind, source_path",
                (patient_uid,),
            ).fetchall()
            assets = []
            for row in asset_rows:
                members = [
                    dict(item)
                    for item in conn.execute(
                        "SELECT member_path, sequence_token, segmentation_family FROM segmentation_members WHERE asset_id = ? ORDER BY member_path",
                        (row["asset_id"],),
                    ).fetchall()
                ]
                assets.append({**dict(row), "segmentation_members": members})
        return {"ok": True, "patient_uid": patient_uid, "assets": assets}

    def _study_payload(self, study_uid: str) -> dict[str, Any]:
        with connect_db(self.root_dir / "catalog" / "mr_rate.sqlite") as conn:
            study_row = conn.execute("SELECT * FROM studies WHERE study_uid = ?", (study_uid,)).fetchone()
            if study_row is None:
                raise KeyError(f"Unknown study_uid: {study_uid}")
            report_row = conn.execute("SELECT * FROM reports WHERE study_uid = ?", (study_uid,)).fetchone()
            series_rows = [
                dict(item)
                for item in conn.execute(
                    "SELECT * FROM series WHERE study_uid = ? ORDER BY series_id",
                    (study_uid,),
                ).fetchall()
            ]
            summary = _read_json_if_exists(study_row["report_summary_path"])
        return {
            "ok": True,
            "study": dict(study_row),
            "report": dict(report_row) if report_row else None,
            "summary": summary,
            "series": series_rows,
        }

    def _analysis_launch_manifest_payload(self, launch_id: str) -> dict[str, Any]:
        manifest_path = _launch_root(self.root_dir) / launch_id / "manifest.json"
        if not manifest_path.exists():
            raise KeyError(f"Unknown launch_id: {launch_id}")
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def _analysis_launch_file_path(self, launch_id: str, file_kind: str) -> Path:
        launch_dir = _launch_root(self.root_dir) / launch_id
        if file_kind == "image":
            path = launch_dir / "image.nii.gz"
        elif file_kind == "seg":
            path = launch_dir / "segmentation.nii.gz"
        else:
            raise KeyError(f"Unsupported launch file kind: {file_kind}")
        if not path.exists():
            raise KeyError(f"Launch file is unavailable: {launch_id}/{file_kind}")
        return path

    def _read_manifest(self, filename: str) -> list[dict[str, Any]]:
        path = self.root_dir / "manifests" / filename
        items: list[dict[str, Any]] = []
        if not path.exists():
            return items
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                items.append(json.loads(line))
        return items

    def _send_json(self, payload: dict[str, Any], *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0:
            return {}
        body = self.rfile.read(content_length)
        if not body:
            return {}
        return json.loads(body.decode("utf-8"))

    def _send_file(self, path: Path, *, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = path.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def serve_api(root: Path, host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> None:
    CatalogAPIHandler.root_dir = root.resolve()
    server = LocalThreadingHTTPServer((host, port), CatalogAPIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="MR-RATE knowledge-layer utility")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init-root", help="Create the output root layout and support files")
    init_parser.add_argument("--root", default=str(DEFAULT_OUTPUT_ROOT))
    init_parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    init_parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    ingest_parser = subparsers.add_parser("ingest", help="Scan MR-RATE data and rebuild the catalog")
    ingest_parser.add_argument("--root", default=str(DEFAULT_OUTPUT_ROOT))
    ingest_parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    ingest_parser.add_argument("--cohort-size", type=int, default=DEFAULT_COHORT_SIZE)
    ingest_parser.add_argument("--cohort-only", action="store_true", help="Only build the catalog for the selected cohort")
    ingest_parser.add_argument("--batch-limit", type=int, default=0, help="Limit ingest to the first N batch CSV files")

    serve_parser = subparsers.add_parser("serve", help="Start the read-only HTTP API")
    serve_parser.add_argument("--root", default=str(DEFAULT_OUTPUT_ROOT))
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = parser.parse_args(argv)
    if args.command == "init-root":
        layout = ensure_root_layout(Path(args.root), Path(args.source_root), port=int(args.port))
        print(json.dumps({"ok": True, "root": str(layout["root"])}, indent=2))
        return 0
    if args.command == "ingest":
        result = ingest_dataset(
            Path(args.root),
            Path(args.source_root),
            cohort_size=int(args.cohort_size),
            cohort_only=bool(args.cohort_only),
            batch_limit=(int(args.batch_limit) or None),
        )
        print(json.dumps({"ok": True, **result}, indent=2))
        return 0
    if args.command == "serve":
        serve_api(Path(args.root), host=str(args.host), port=int(args.port))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
