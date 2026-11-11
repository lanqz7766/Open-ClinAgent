#!/usr/bin/env python3
"""Initialize a local-only brain tumor segmentation dataset workspace."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

DATASET_LAYOUT = [
    "raw/UPENN_GBM",
    "raw/UCSF_PDGM",
    "raw/BraTS_GLI_2024",
    "raw/TCGA_GBM_BraTS",
    "manifests/official_downloads",
    "manifests/checksums",
    "manifests/license_and_citations",
    "working/normalized_nifti",
    "working/nnunet_raw",
    "working/nnunet_preprocessed",
    "working/splits",
    "working/qc_reports",
    "models/nnunet_glioma_mixed_v1",
    "inference_service/releases",
    "inference_service/test_cases",
]

SOURCE_CATALOG = {
    "UPENN_GBM": {
        "role": "GBM-specific backbone cohort",
        "official_url": "https://www.cancerimagingarchive.net/collection/upenn-gbm/",
        "preferred_download": "TCIA/NBIA official collection manifest",
        "notes": "Keep TCIA manifests, citation text, and any checksums in manifests/.",
    },
    "UCSF_PDGM": {
        "role": "Diffuse glioma generalization cohort",
        "official_url": "https://www.cancerimagingarchive.net/collection/ucsf-pdgm/",
        "preferred_download": "TCIA/NBIA official collection manifest",
        "notes": "Confirm annotation availability and label semantics before mixing into training.",
    },
    "BraTS_GLI_2024": {
        "role": "Standard adult glioma benchmark cohort",
        "official_url": "https://www.synapse.org/Synapse%3Asyn53708249/challenge/",
        "preferred_download": "Synapse official challenge files",
        "notes": "Requires Synapse account/access acceptance before download.",
    },
    "TCGA_GBM_BraTS": {
        "role": "Compact GBM external validation/prototype cohort",
        "official_url": "https://www.cancerimagingarchive.net/analysis-result/brats-tcga-gbm/",
        "preferred_download": "TCIA/NBIA official analysis-result manifest",
        "notes": "Use for external validation after leakage checks.",
    },
}

LOCAL_README = """# Brain Tumor Segmentation Workspace

This directory is a local-only research workspace for public glioma/GBM MRI segmentation data.

Rules:

- Do not copy MRI data, segmentations, derived reports, screenshots, manifests with local paths, or model weights into the ClinAgent repository.
- Keep official source manifests under `manifests/official_downloads/`.
- Keep citation/license text under `manifests/license_and_citations/`.
- Keep raw downloads immutable under `raw/`; write normalized training data under `working/`.
- Store trained model artifacts under `models/` or an external model registry.

Expected normalized case format:

```text
case_id/
  t1n.nii.gz
  t1c.nii.gz
  t2w.nii.gz
  t2f.nii.gz
  seg.nii.gz
  metadata.json
```

Download notes:

- TCIA/NBIA collections should be downloaded from official TCIA collection or analysis-result manifests.
- BraTS-GLI should be downloaded from the official Synapse challenge page after access terms are accepted.
- Save any credential files outside this directory unless the credential manager explicitly requires a local cache.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        default=os.getenv("BRAIN_TUMOR_DATA_ROOT", ""),
        help="Dataset workspace root. Defaults to BRAIN_TUMOR_DATA_ROOT.",
    )
    args = parser.parse_args()

    if not args.root:
        raise SystemExit("Set --root or BRAIN_TUMOR_DATA_ROOT.")

    root = Path(args.root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    for rel in DATASET_LAYOUT:
        (root / rel).mkdir(parents=True, exist_ok=True)

    (root / "manifests" / "source_catalog.json").write_text(
        json.dumps(SOURCE_CATALOG, indent=2) + "\n",
        encoding="utf-8",
    )
    readme_path = root / "README.local.md"
    if not readme_path.exists():
        readme_path.write_text(LOCAL_README, encoding="utf-8")

    print(f"Initialized brain tumor dataset workspace: {root}")
    print(f"Created {len(DATASET_LAYOUT)} directories")


if __name__ == "__main__":
    main()
