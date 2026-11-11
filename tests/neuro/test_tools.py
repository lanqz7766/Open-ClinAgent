from __future__ import annotations

import csv
import json
from pathlib import Path

import nibabel as nib
import numpy as np
import pytest

from clinagent.families.neuro.reference_tables import build_runtime_reference_table, load_master_records
from clinagent.families.neuro.config import NeuroAgentConfig
from clinagent.families.neuro.tools import BrainSegmentationTool, StructuralSegmentationAdapter, VolumetricAnalysisTool


def _write_segmentation(path: Path, data: np.ndarray, affine: np.ndarray | None = None) -> Path:
    image = nib.Nifti1Image(data.astype(np.int16), affine if affine is not None else np.eye(4))
    nib.save(image, str(path))
    return path


def _write_normative_table(path: Path) -> Path:
    payload = {
        "_meta": {"note": "test fixture"},
        "left_hippocampus": {"_direction": "low", "M": {"70-79": {"mean": 12.0, "std": 2.0}}},
        "right_hippocampus": {"_direction": "low", "M": {"70-79": {"mean": 8.0, "std": 2.0}}},
        "left_lateral_ventricle": {"_direction": "high", "M": {"70-79": {"mean": 4.0, "std": 1.0}}},
        "hippocampus": {"_direction": "low", "M": {"70-79": {"mean": 20.0, "std": 2.0}}},
        "total_brain_volume": {"_direction": "low", "M": {"70-79": {"mean": 18.0, "std": 3.0}}},
    }
    path.write_text(json.dumps(payload))
    return path


def test_brain_segmentation_tool_returns_expected_volumes(tmp_path: Path) -> None:
    seg = np.zeros((4, 4, 4), dtype=np.int16)
    seg.ravel()[:12] = 230
    seg.ravel()[12:20] = 229
    seg.ravel()[20:24] = 234
    affine = np.diag([1.0, 2.0, 3.0, 1.0])
    seg_path = _write_segmentation(tmp_path / "seg.nii.gz", seg, affine=affine)

    result = BrainSegmentationTool().run(str(seg_path))

    assert result["voxel_volume_mm3"] == pytest.approx(6.0)
    region_by_name = {item["name"]: item for item in result["regions"]}
    assert region_by_name["left_hippocampus"]["voxel_count"] == 12
    assert region_by_name["left_hippocampus"]["volume_mm3"] == pytest.approx(72.0)
    assert region_by_name["right_hippocampus"]["volume_mm3"] == pytest.approx(48.0)
    grouped_region_by_name = {item["name"]: item for item in result["grouped_regions"]}
    assert grouped_region_by_name["hippocampus"]["volume_mm3"] == pytest.approx(120.0)
    assert result["total_brain_voxels"] == 20
    assert result["total_brain_volume_mm3"] == pytest.approx(120.0)


def test_volumetric_analysis_computes_expected_statistics(tmp_path: Path) -> None:
    normative_path = _write_normative_table(tmp_path / "normative.json")
    tool = VolumetricAnalysisTool(str(normative_path))
    segmentation_result = {
        "regions": [
            {"name": "left_hippocampus", "volume_mm3": 10.0},
            {"name": "right_hippocampus", "volume_mm3": 6.0},
            {"name": "left_lateral_ventricle", "volume_mm3": 5.0},
        ],
        "total_brain_volume_mm3": 18.0,
    }

    result = tool.run(segmentation_result=segmentation_result, patient_age=72, patient_sex="M")
    region_by_name = {item["name"]: item for item in result["interpreted_regions"]}

    assert len(result["regions"]) == 3
    assert len(result["interpreted_regions"]) == 4

    assert region_by_name["left_hippocampus"]["z_score"] == pytest.approx(-1.0)
    assert region_by_name["left_hippocampus"]["interpretation"] == "mildly reduced"
    assert region_by_name["right_hippocampus"]["z_score"] == pytest.approx(-1.0)
    assert region_by_name["left_lateral_ventricle"]["interpretation"] == "mildly enlarged"
    assert region_by_name["total_brain_volume"]["interpretation"] == "within normal limits"
    assert "Reference-based comparative volumetry flagged" in result["summary"]
    assert result["reference_bucket"] == {"age_decade": "70-79", "sex": "M"}


def test_default_normative_table_path_is_resolvable() -> None:
    config = NeuroAgentConfig()

    assert Path(config.normative_table_path).exists()
    VolumetricAnalysisTool(config.normative_table_path)


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        (96.0, "within normal limits"),
        (89.0, "mildly reduced"),
        (82.0, "moderately reduced"),
        (70.0, "severely reduced"),
    ],
)
def test_volumetric_interpretation_thresholds(tmp_path: Path, volume: float, expected: str) -> None:
    normative_path = tmp_path / "normative.json"
    normative_path.write_text(
        json.dumps(
            {
                "_meta": {"note": "test fixture"},
                "left_hippocampus": {"_direction": "low", "M": {"70-79": {"mean": 100.0, "std": 10.0}}},
            }
        )
    )
    tool = VolumetricAnalysisTool(str(normative_path))
    segmentation_result = {
        "regions": [{"name": "left_hippocampus", "volume_mm3": volume}],
        "total_brain_volume_mm3": volume,
    }

    result = tool.run(segmentation_result=segmentation_result, patient_age=72, patient_sex="M")

    region = next(item for item in result["interpreted_regions"] if item["name"] == "left_hippocampus")
    assert region["interpretation"] == expected


@pytest.mark.parametrize(
    ("volume", "expected"),
    [
        (104.0, "within normal limits"),
        (111.0, "mildly enlarged"),
        (118.0, "moderately enlarged"),
        (130.0, "severely enlarged"),
    ],
)
def test_volumetric_interpretation_thresholds_for_high_direction(
    tmp_path: Path,
    volume: float,
    expected: str,
) -> None:
    normative_path = tmp_path / "normative.json"
    normative_path.write_text(
        json.dumps(
            {
                "_meta": {"note": "test fixture"},
                "left_lateral_ventricle": {"_direction": "high", "M": {"70-79": {"mean": 100.0, "std": 10.0}}},
            }
        )
    )
    tool = VolumetricAnalysisTool(str(normative_path))
    segmentation_result = {
        "regions": [{"name": "left_lateral_ventricle", "volume_mm3": volume}],
        "total_brain_volume_mm3": 0.0,
    }

    result = tool.run(segmentation_result=segmentation_result, patient_age=72, patient_sex="M")

    region = next(item for item in result["interpreted_regions"] if item["name"] == "left_lateral_ventricle")
    assert region["interpretation"] == expected


def test_structural_segmentation_adapter_filters_excluded_labels_and_exports_csv(tmp_path: Path) -> None:
    seg = np.zeros((4, 4, 4), dtype=np.int16)
    seg.ravel()[:12] = 1
    seg.ravel()[12:20] = 2
    seg.ravel()[20:24] = 3
    seg_path = _write_segmentation(tmp_path / "seg.nii.gz", seg)
    label_schema_path = tmp_path / "labels.json"
    label_schema_path.write_text(
        json.dumps(
            {
                "label_schema_version": "1.0.0",
                "labels": [
                    {"label_id": 1, "label_name": "left_hippocampus", "group": "hippocampus", "hemisphere": "left"},
                    {"label_id": 2, "label_name": "ctx-lh-precentral", "group": "cortex", "hemisphere": "left"},
                    {"label_id": 3, "label_name": "right_lateral_ventricle", "group": "ventricles", "hemisphere": "right"},
                ],
            }
        )
    )

    adapter = StructuralSegmentationAdapter()
    result = adapter.run(seg_nifti_path=str(seg_path), label_schema_path=str(label_schema_path))

    assert [region["label_name"] for region in result["regions"]] == ["left_hippocampus", "right_lateral_ventricle"]
    assert [group["name"] for group in result["grouped_regions"]] == ["hippocampus", "ventricles"]
    export_path = Path(
        adapter.export_regions_csv(
            destination_path=tmp_path / "structural-regions.csv",
            regions=result["regions"],
            case_id="case-1",
            patient_id="patient-1",
            study_id="study-1",
        )
    )
    rows = list(csv.DictReader(export_path.open("r", encoding="utf-8")))
    assert len(rows) == 2
    assert {row["label_name"] for row in rows} == {"left_hippocampus", "right_lateral_ventricle"}


def test_runtime_reference_builder_publishes_only_approved_tier_a_rows(tmp_path: Path) -> None:
    master_path = tmp_path / "master.csv"
    master_path.write_text(
        "\n".join(
            [
                (
                    "roi_name,roi_mapping_scope,sex,age_start,age_end,mean_mm3,std_mm3,n,source_type,"
                    "source_citation,source_url,segmentation_protocol,label_definition_match,icv_adjustment,"
                    "scanner_scope,field_strength,population_notes,evidence_tier,fit_for_runtime,"
                    "review_status,last_reviewed_on,reviewer"
                ),
                (
                    "left_hippocampus,exact,M,70,79,100.0,10.0,150,cohort,"
                    "Healthy cohort A,https://example.org/a,same-pipeline,exact,residual,"
                    "single_site,3T,healthy controls,Tier A,true,approved,2026-04-10,reviewer-a"
                ),
                (
                    "left_hippocampus,exact,M,70,79,98.0,12.0,220,literature,"
                    "Healthy cohort B,https://example.org/b,other-pipeline,approximate,none,"
                    "multisite,mixed,healthy controls,Tier B,true,approved,2026-04-10,reviewer-b"
                ),
                (
                    "left_hippocampus,exact,F,70,79,90.0,11.0,95,cohort,"
                    "Healthy cohort C,https://example.org/c,same-pipeline,exact,residual,"
                    "single_site,3T,healthy controls,Tier A,true,approved,2026-04-10,reviewer-c"
                ),
            ]
        ),
        encoding="utf-8",
    )

    payload = build_runtime_reference_table(
        load_master_records(master_path),
        generated_from=str(master_path),
        alignment_source="alignment-source",
    )

    assert payload["_meta"]["published_region_count"] == 1
    assert payload["left_hippocampus"]["M"]["70-79"]["mean"] == pytest.approx(100.0)
    assert "F" not in payload["left_hippocampus"]


def test_volumetric_analysis_handles_empty_published_reference_table(tmp_path: Path) -> None:
    normative_path = tmp_path / "normative.json"
    normative_path.write_text(
        json.dumps(
            {
                "_meta": {
                    "note": "generated runtime table",
                    "normalization_limits": ["icv adjustment missing"],
                }
            }
        )
    )
    tool = VolumetricAnalysisTool(str(normative_path))

    result = tool.run(
        segmentation_result={"regions": [{"name": "left_hippocampus", "volume_mm3": 100.0}], "total_brain_volume_mm3": 0.0},
        patient_age=72,
        patient_sex="M",
    )

    assert result["interpreted_regions"] == []
    assert result["summary"] == "No approved research-use reference values are available for the referenced regions."
    assert result["normalization_limits"] == ["icv adjustment missing"]
