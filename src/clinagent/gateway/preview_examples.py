"""Explicitly published, administrator-approved upload examples."""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from clinagent.gateway.brain_tumor_uploads import UPLOAD_MODALITIES, _sanitize_nifti


def example_archives() -> list[tuple[dict[str, Any], Path]]:
    configured = os.getenv("CLINAGENT_UPLOAD_EXAMPLES_ROOT", "").strip()
    if not configured:
        return []
    root = Path(configured).expanduser().resolve()
    catalog = root / "catalog.json"
    if not catalog.is_file():
        return []
    rows = json.loads(catalog.read_text(encoding="utf-8"))["examples"]
    examples = []
    for row in rows:
        example_id = str(row["id"])
        if not re.fullmatch(r"example_[0-9]{2}", example_id):
            raise ValueError("Invalid upload example ID.")
        archive = (root / f"{example_id}.zip").resolve()
        if archive.parent != root or not archive.is_file():
            raise ValueError("Upload example archive is unavailable.")
        examples.append(({
            "id": example_id,
            "label": f"Example {example_id[-2:]}",
            "visit_count": int(row.get("visit_count", 1)),
            "file_count": 4 * int(row.get("visit_count", 1)),
            "size_bytes": archive.stat().st_size,
            "download_url": f"/api/demo/brain-tumor/upload-examples/{example_id}/download",
        }, archive))
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Package an approved, de-identified four-modality upload example.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--id", required=True)
    parser.add_argument("--approved-deidentified", action="store_true", required=True,
                        help="Confirm permission to share the images. Header cleaning does not remove identifiers embedded in pixels.")
    for key in UPLOAD_MODALITIES:
        parser.add_argument(f"--{key}", type=Path)
    parser.add_argument("--visit", type=Path, nargs=4, action="append", metavar=("T1", "T1C", "T2", "FLAIR"),
                        help="Repeat for two to six same-patient visits in chronological order. Dates are entered by the uploader.")
    args = parser.parse_args()
    if not re.fullmatch(r"example_[0-9]{2}", args.id):
        parser.error("ID must use example_01 format.")
    keys = ("t1n", "t1c", "t2w", "t2f")
    single = [getattr(args, key) for key in keys]
    if args.visit:
        if any(single) or not 1 <= len(args.visit) <= 6:
            parser.error("Use --visit up to six times, without individual modality options.")
        visits = [dict(zip(keys, paths)) for paths in args.visit]
    else:
        if not all(single):
            parser.error("Provide all four modality options or repeat --visit T1 T1C T2 FLAIR.")
        visits = [dict(zip(keys, single))]
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    archive_path = root / f"{args.id}.zip"
    if archive_path.exists():
        parser.error("Example already exists; choose a new ID or output directory.")
    names = {"t1n": "T1", "t1c": "T1c", "t2w": "T2", "t2f": "FLAIR"}
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        staging = Path(tmp)
        with zipfile.ZipFile(staging / "example.zip", "w", compression=zipfile.ZIP_STORED) as archive:
            for index, visit in enumerate(visits, start=1):
                prefix = f"{args.id}/visit_{index:02d}" if len(visits) > 1 else args.id
                for key, label in names.items():
                    path = staging / f"{label}.nii.gz"
                    _sanitize_nifti(visit[key], path)
                    archive.write(path, f"{prefix}/{label}.nii.gz")
            archive.writestr(f"{args.id}/README.txt", (
                f"ClinAgent research preview: {len(visits)} visit(s), four MRI modalities per visit.\n"
                "1. Open Upload MRI.\n"
                "2. Drop this ZIP directly, or select it with Choose ZIP or files. Extracted folders and files are also supported.\n"
                "3. Confirm each visit's order and T1, T1c, T2 and FLAIR mapping.\n"
                "4. Dates are optional; leave unknown dates blank. Confirm same-patient provenance and submit.\n"
                "These examples are for testing, not clinical diagnosis.\n"
                "No reference mask is included. Segmentation runs after upload.\n"
            ))
        (staging / "example.zip").replace(archive_path)
    catalog = root / "catalog.json"
    rows = json.loads(catalog.read_text())["examples"] if catalog.exists() else []
    rows.append({"id": args.id, "visit_count": len(visits)})
    temporary = root / "catalog.next.json"
    temporary.write_text(json.dumps({"examples": rows}, indent=2), encoding="utf-8")
    temporary.replace(catalog)
    print(json.dumps({"id": args.id, "size_bytes": archive_path.stat().st_size}))


if __name__ == "__main__":
    main()
