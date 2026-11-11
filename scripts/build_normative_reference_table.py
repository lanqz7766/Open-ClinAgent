#!/usr/bin/env python3
"""Build the published research-use volumetric reference table from the master CSV."""
from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TABLES_PATH = REPO_ROOT / "src" / "clinagent" / "families" / "neuro" / "reference_tables.py"

spec = importlib.util.spec_from_file_location("clinagent_reference_tables", REFERENCE_TABLES_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Unable to load reference table helpers from {REFERENCE_TABLES_PATH}")
reference_tables = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reference_tables
spec.loader.exec_module(reference_tables)
load_master_records = reference_tables.load_master_records
write_runtime_reference_table = reference_tables.write_runtime_reference_table

DEFAULT_ALIGNMENT_SOURCE = "Official label naming derived from https://huggingface.co/nvidia/NV-Segment-CTMR/blob/main/metadata.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="configs/normative_brain_volumes_master.csv",
        help="Path to the master CSV of candidate reference rows.",
    )
    parser.add_argument(
        "--output",
        default="configs/normative_brain_volumes.json",
        help="Path to the published runtime JSON.",
    )
    parser.add_argument(
        "--alignment-source",
        default=DEFAULT_ALIGNMENT_SOURCE,
        help="Label ontology alignment note stored in the generated JSON metadata.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    records = load_master_records(input_path)
    payload = write_runtime_reference_table(
        records,
        generated_from=str(input_path),
        alignment_source=args.alignment_source,
        destination=output_path,
    )
    print(
        f"Published {payload['_meta']['published_record_count']} approved age/sex buckets "
        f"across {payload['_meta']['published_region_count']} regions to {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
