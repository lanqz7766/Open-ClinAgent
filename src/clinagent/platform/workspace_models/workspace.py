"""Define the normalized workspace contract shared across ingest and frontend layers.
Input: patient/timepoint metadata, file paths, report text, and extracted metrics from assembly code.
Output: dataclass-based WorkspaceContract objects independent of any source-specific dataset layout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class TimepointData:
    date: str
    label: str
    imaging_paths: list[str] = field(default_factory=list)
    report_text: str | None = None
    segmentation_path: str | None = None
    extracted_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorkspaceContract:
    workspace_id: str
    workflow_type: str
    patient_id: str
    timepoints: list[TimepointData] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
