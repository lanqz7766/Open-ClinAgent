"""Brain segmentation tool — loads and processes NV-Segment-CTMR segmentations."""
from __future__ import annotations

from pathlib import Path
import re

import nibabel as nib
import numpy as np

from clinagent.families.neuro.tools.base_tool import BaseTool

# Official brain-region subset from NVIDIA NV-Segment-CTMR metadata.json
# https://huggingface.co/nvidia/NV-Segment-CTMR/blob/main/metadata.json
OFFICIAL_REGION_LABELS: dict[int, str] = {
    214: "3rd-Ventricle",
    215: "4th-Ventricle",
    216: "Right-Accumbens-Area",
    217: "Left-Accumbens-Area",
    218: "Right-Amygdala",
    219: "Left-Amygdala",
    220: "Brain-Stem",
    221: "Right-Caudate",
    222: "Left-Caudate",
    223: "Right-Cerebellum-Exterior",
    224: "Left-Cerebellum-Exterior",
    225: "Right-Cerebellum-White-Matter",
    226: "Left-Cerebellum-White-Matter",
    227: "Right-Cerebral-White-Matter",
    228: "Left-Cerebral-White-Matter",
    229: "Right-Hippocampus",
    230: "Left-Hippocampus",
    231: "Right-Inf-Lat-Vent",
    232: "Left-Inf-Lat-Vent",
    233: "Right-Lateral-Ventricle",
    234: "Left-Lateral-Ventricle",
    235: "Right-Pallidum",
    236: "Left-Pallidum",
    237: "Right-Putamen",
    238: "Left-Putamen",
    239: "Right-Thalamus-Proper",
    240: "Left-Thalamus-Proper",
    241: "Right-Ventral-DC",
    242: "Left-Ventral-DC",
    243: "Cerebellar-Vermal-Lobules-I-V",
    244: "Cerebellar-Vermal-Lobules-VI-VII",
    245: "Cerebellar-Vermal-Lobules-VIII-X",
    246: "Left-Basal-Forebrain",
    247: "Right-Basal-Forebrain",
    248: "Right-ACgG--anterior-cingulate-gyrus",
    249: "Left-ACgG--anterior-cingulate-gyrus",
    250: "Right-AIns--anterior-insula",
    251: "Left-AIns--anterior-insula",
    252: "Right-AOrG--anterior-orbital-gyrus",
    253: "Left-AOrG--anterior-orbital-gyrus",
    254: "Right-AnG---angular-gyrus",
    255: "Left-AnG---angular-gyrus",
    256: "Right-Calc--calcarine-cortex",
    257: "Left-Calc--calcarine-cortex",
    258: "Right-CO----central-operculum",
    259: "Left-CO----central-operculum",
    260: "Right-Cun---cuneus",
    261: "Left-Cun---cuneus",
    262: "Right-Ent---entorhinal-area",
    263: "Left-Ent---entorhinal-area",
    264: "Right-FO----frontal-operculum",
    265: "Left-FO----frontal-operculum",
    266: "Right-FRP---frontal-pole",
    267: "Left-FRP---frontal-pole",
    268: "Right-FuG---fusiform-gyrus",
    269: "Left-FuG---fusiform-gyrus",
    270: "Right-GRe---gyrus-rectus",
    271: "Left-GRe---gyrus-rectus",
    272: "Right-IOG---inferior-occipital-gyrus",
    273: "Left-IOG---inferior-occipital-gyrus",
    274: "Right-ITG---inferior-temporal-gyrus",
    275: "Left-ITG---inferior-temporal-gyrus",
    276: "Right-LiG---lingual-gyrus",
    277: "Left-LiG---lingual-gyrus",
    278: "Right-LOrG--lateral-orbital-gyrus",
    279: "Left-LOrG--lateral-orbital-gyrus",
    280: "Right-MCgG--middle-cingulate-gyrus",
    281: "Left-MCgG--middle-cingulate-gyrus",
    282: "Right-MFC---medial-frontal-cortex",
    283: "Left-MFC---medial-frontal-cortex",
    284: "Right-MFG---middle-frontal-gyrus",
    285: "Left-MFG---middle-frontal-gyrus",
    286: "Right-MOG---middle-occipital-gyrus",
    287: "Left-MOG---middle-occipital-gyrus",
    288: "Right-MOrG--medial-orbital-gyrus",
    289: "Left-MOrG--medial-orbital-gyrus",
    290: "Right-MPoG--postcentral-gyrus",
    291: "Left-MPoG--postcentral-gyrus",
    292: "Right-MPrG--precentral-gyrus",
    293: "Left-MPrG--precentral-gyrus",
    294: "Right-MSFG--superior-frontal-gyrus",
    295: "Left-MSFG--superior-frontal-gyrus",
    296: "Right-MTG---middle-temporal-gyrus",
    297: "Left-MTG---middle-temporal-gyrus",
    298: "Right-OCP---occipital-pole",
    299: "Left-OCP---occipital-pole",
    300: "Right-OFuG--occipital-fusiform-gyrus",
    301: "Left-OFuG--occipital-fusiform-gyrus",
    302: "Right-OpIFG-opercular-part-of-the-IFG",
    303: "Left-OpIFG-opercular-part-of-the-IFG",
    304: "Right-OrIFG-orbital-part-of-the-IFG",
    305: "Left-OrIFG-orbital-part-of-the-IFG",
    306: "Right-PCgG--posterior-cingulate-gyrus",
    307: "Left-PCgG--posterior-cingulate-gyrus",
    308: "Right-PCu---precuneus",
    309: "Left-PCu---precuneus",
    310: "Right-PHG---parahippocampal-gyrus",
    311: "Left-PHG---parahippocampal-gyrus",
    312: "Right-PIns--posterior-insula",
    313: "Left-PIns--posterior-insula",
    314: "Right-PO----parietal-operculum",
    315: "Left-PO----parietal-operculum",
    316: "Right-PoG---postcentral-gyrus",
    317: "Left-PoG---postcentral-gyrus",
    318: "Right-POrG--posterior-orbital-gyrus",
    319: "Left-POrG--posterior-orbital-gyrus",
    320: "Right-PP----planum-polare",
    321: "Left-PP----planum-polare",
    322: "Right-PrG---precentral-gyrus",
    323: "Left-PrG---precentral-gyrus",
    324: "Right-PT----planum-temporale",
    325: "Left-PT----planum-temporale",
    326: "Right-SCA---subcallosal-area",
    327: "Left-SCA---subcallosal-area",
    328: "Right-SFG---superior-frontal-gyrus",
    329: "Left-SFG---superior-frontal-gyrus",
    330: "Right-SMC---supplementary-motor-cortex",
    331: "Left-SMC---supplementary-motor-cortex",
    332: "Right-SMG---supramarginal-gyrus",
    333: "Left-SMG---supramarginal-gyrus",
    334: "Right-SOG---superior-occipital-gyrus",
    335: "Left-SOG---superior-occipital-gyrus",
    336: "Right-SPL---superior-parietal-lobule",
    337: "Left-SPL---superior-parietal-lobule",
    338: "Right-STG---superior-temporal-gyrus",
    339: "Left-STG---superior-temporal-gyrus",
    340: "Right-TMP---temporal-pole",
    341: "Left-TMP---temporal-pole",
    342: "Right-TrIFG-triangular-part-of-the-IFG",
    343: "Left-TrIFG-triangular-part-of-the-IFG",
    344: "Right-TTG---transverse-temporal-gyrus",
    345: "Left-TTG---transverse-temporal-gyrus",
}

NORMALIZED_NAME_OVERRIDES: dict[str, str] = {
    "3rd-Ventricle": "third_ventricle",
    "4th-Ventricle": "fourth_ventricle",
    "Brain-Stem": "brain_stem",
    "Right-Inf-Lat-Vent": "right_inferior_lateral_ventricle",
    "Left-Inf-Lat-Vent": "left_inferior_lateral_ventricle",
    "Right-Thalamus-Proper": "right_thalamus",
    "Left-Thalamus-Proper": "left_thalamus",
    "Right-Ventral-DC": "right_ventral_diencephalon",
    "Left-Ventral-DC": "left_ventral_diencephalon",
    "Cerebellar-Vermal-Lobules-I-V": "cerebellar_vermal_lobules_i_v",
    "Cerebellar-Vermal-Lobules-VI-VII": "cerebellar_vermal_lobules_vi_vii",
    "Cerebellar-Vermal-Lobules-VIII-X": "cerebellar_vermal_lobules_viii_x",
    "Right-Cerebellum-Exterior": "right_cerebellum_cortex",
    "Left-Cerebellum-Exterior": "left_cerebellum_cortex",
}

GROUP_DISPLAY_NAMES: dict[str, str] = {
    "left_cerebral_cortex": "Left cerebral cortex",
    "right_cerebral_cortex": "Right cerebral cortex",
    "cortex": "Cerebral cortex",
    "hippocampus": "Hippocampi",
    "ventricles": "Ventricular system",
    "white_matter": "Cerebral white matter",
    "deep_gray": "Deep gray nuclei",
    "cerebellum": "Cerebellum",
    "brainstem": "Brainstem",
}

DEEP_GRAY_REGIONS = {
    "left_thalamus",
    "right_thalamus",
    "left_caudate",
    "right_caudate",
    "left_putamen",
    "right_putamen",
    "left_pallidum",
    "right_pallidum",
}

VENTRICULAR_REGIONS = {
    "third_ventricle",
    "fourth_ventricle",
    "left_lateral_ventricle",
    "right_lateral_ventricle",
    "left_inferior_lateral_ventricle",
    "right_inferior_lateral_ventricle",
}


def _normalize_region_name(official_name: str) -> str:
    if official_name in NORMALIZED_NAME_OVERRIDES:
        return NORMALIZED_NAME_OVERRIDES[official_name]
    if "--" in official_name or "---" in official_name:
        hemisphere, remainder = official_name.split("-", 1)
        abbreviation, description = re.split(r"-{2,}", remainder, maxsplit=1)
        normalized = f"{hemisphere.lower()}_{abbreviation.lower()}_{description.replace('-', '_').lower()}"
        return re.sub(r"_+", "_", normalized).strip("_")
    normalized = official_name.replace("Right-", "right_").replace("Left-", "left_").replace("-", "_").lower()
    return re.sub(r"_+", "_", normalized).strip("_")


def _display_name(name: str) -> str:
    return name.replace("_", " ")


def _region_groups(label_id: int, region_name: str) -> list[str]:
    groups: list[str] = []
    if region_name in {"left_hippocampus", "right_hippocampus"}:
        groups.append("hippocampus")
    if region_name in VENTRICULAR_REGIONS:
        groups.append("ventricles")
    if region_name in {"left_cerebral_white_matter", "right_cerebral_white_matter"}:
        groups.append("white_matter")
    if region_name in DEEP_GRAY_REGIONS:
        groups.append("deep_gray")
    if region_name == "brain_stem":
        groups.append("brainstem")
    if region_name.startswith(("left_cerebellum_", "right_cerebellum_", "cerebellar_vermal_")):
        groups.append("cerebellum")
    if 248 <= label_id <= 345:
        groups.append("cortex")
        if region_name.startswith("left_"):
            groups.append("left_cerebral_cortex")
        elif region_name.startswith("right_"):
            groups.append("right_cerebral_cortex")
    return groups


class BrainSegmentationTool(BaseTool):
    """Load a segmentation NIfTI and extract per-region voxel and volume counts."""

    OFFICIAL_REGION_LABELS = OFFICIAL_REGION_LABELS
    REGION_LABELS = {
        label_id: _normalize_region_name(official_name)
        for label_id, official_name in OFFICIAL_REGION_LABELS.items()
    }
    _CSF_TOKENS = ("ventricle",)

    @property
    def name(self) -> str:
        return "brain_segmentation"

    @property
    def description(self) -> str:
        return "Load brain segmentation masks and compute per-region voxel and volume counts"

    @property
    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "seg_nifti_path": {
                    "type": "string",
                    "description": "Path to the segmentation NIfTI file",
                },
                "voxel_size_mm": {
                    "type": ["array", "null"],
                    "description": "Optional voxel dimensions in mm for x, y, z order",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "required": ["seg_nifti_path"],
            "additionalProperties": False,
        }

    def run(self, seg_nifti_path: str, voxel_size_mm: tuple[float, float, float] | None = None) -> dict:
        """Read the segmentation volume and compute JSON-serializable region summaries."""
        seg_path = Path(seg_nifti_path)
        img = nib.load(str(seg_path))
        img = nib.as_closest_canonical(img)
        data = np.asarray(img.get_fdata(), dtype=np.int32)
        if voxel_size_mm is None:
            voxel_size_mm = tuple(float(z) for z in img.header.get_zooms()[:3])
        voxel_volume_mm3 = float(np.prod(voxel_size_mm))

        regions: list[dict] = []
        grouped_regions: dict[str, dict] = {}
        total_brain_voxels = 0
        total_brain_volume_mm3 = 0.0

        labels, counts = np.unique(data, return_counts=True)
        for label_id, voxel_count in zip(labels.tolist(), counts.tolist(), strict=True):
            if label_id == 0:
                continue
            official_name = self.OFFICIAL_REGION_LABELS.get(label_id, f"unknown_region_{label_id}")
            region_name = self.REGION_LABELS.get(label_id, f"unknown_region_{label_id}")
            volume_mm3 = float(voxel_count * voxel_volume_mm3)
            groups = _region_groups(label_id, region_name)
            region = {
                "label_id": int(label_id),
                "name": region_name,
                "display_name": _display_name(region_name),
                "official_name": official_name,
                "groups": groups,
                "voxel_count": int(voxel_count),
                "volume_mm3": volume_mm3,
            }
            regions.append(region)

            for group_name in groups:
                if group_name not in grouped_regions:
                    grouped_regions[group_name] = {
                        "name": group_name,
                        "display_name": GROUP_DISPLAY_NAMES[group_name],
                        "source_labels": [],
                        "member_regions": [],
                        "voxel_count": 0,
                        "volume_mm3": 0.0,
                    }
                grouped_regions[group_name]["source_labels"].append(int(label_id))
                grouped_regions[group_name]["member_regions"].append(region_name)
                grouped_regions[group_name]["voxel_count"] += int(voxel_count)
                grouped_regions[group_name]["volume_mm3"] += volume_mm3

            if not self._is_csf_region(region_name):
                total_brain_voxels += int(voxel_count)
                total_brain_volume_mm3 += volume_mm3

        regions.sort(key=lambda item: item["label_id"])
        grouped_region_list = sorted(grouped_regions.values(), key=lambda item: item["name"])
        for item in grouped_region_list:
            item["source_labels"].sort()
            item["member_regions"] = sorted(set(item["member_regions"]))

        return {
            "regions": regions,
            "grouped_regions": grouped_region_list,
            "voxel_size_mm": [float(value) for value in voxel_size_mm],
            "voxel_volume_mm3": voxel_volume_mm3,
            "total_brain_voxels": total_brain_voxels,
            "total_brain_volume_mm3": total_brain_volume_mm3,
            "segmentation_path": str(seg_path),
        }

    @classmethod
    def _is_csf_region(cls, label_name: str) -> bool:
        lowered = label_name.lower()
        return any(token in lowered for token in cls._CSF_TOKENS)
