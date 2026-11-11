#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from typing import Iterable

from clinagent.families.neuro.report_demo import NeuroReportDemoStore


def _selected_records(store: NeuroReportDemoStore, *, case_ids: set[str] | None, patient_ids: set[str] | None) -> Iterable[tuple[str, str]]:
    for patient_id, studies in sorted(store._records_by_patient.items()):
        if patient_ids and patient_id not in patient_ids:
            continue
        for record in studies:
            if case_ids and record.case_id not in case_ids:
                continue
            yield patient_id, record.study_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate preload structural demo segmentations with the remote structural segmenter.")
    parser.add_argument("--case-id", action="append", default=[], help="Specific case_id values to refresh, e.g. 1278:CTH7YTCQQH")
    parser.add_argument("--patient-id", action="append", default=[], help="Specific patient IDs to refresh")
    parser.add_argument("--limit", type=int, default=None, help="Optional cap on the number of studies to process")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing generated segmentations")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "cpu"], help="Segmentation service device mode")
    parser.add_argument("--engine", default="auto", help="Segmentation service engine selector")
    parser.add_argument("--json", action="store_true", help="Emit one JSON object per processed study")
    args = parser.parse_args()

    store = NeuroReportDemoStore()
    case_ids = set(args.case_id) or None
    patient_ids = set(args.patient_id) or None

    processed = 0
    for patient_id, study_id in _selected_records(store, case_ids=case_ids, patient_ids=patient_ids):
        if args.limit is not None and processed >= args.limit:
            break
        result = store.regenerate_structural_demo_segmentation(
            patient_id=patient_id,
            study_id=study_id,
            overwrite=args.overwrite,
            device=args.device,
            engine=args.engine,
        )
        if args.json:
            print(json.dumps(result, ensure_ascii=True))
        else:
            print(f"{result['status']:>9}  {result['case_id']}  {result['seg_path']}")
        processed += 1

    print(f"processed={processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
