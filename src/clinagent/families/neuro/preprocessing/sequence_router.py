"""Identify MRI sequence type from metadata or filename."""
from __future__ import annotations

import re
from enum import Enum
from typing import Any


class MRISequence(Enum):
    """Supported MRI sequence classes for the Sprint 1 neuro pipeline."""

    T1W = "T1w"
    T2W = "T2w"
    FLAIR = "FLAIR"
    SWI = "SWI"
    MRA = "MRA"
    UNKNOWN = "unknown"


class SequenceRouter:
    """Identify MRI sequences from lightweight metadata heuristics."""

    _PATTERNS: list[tuple[MRISequence, re.Pattern[str]]] = [
        (MRISequence.FLAIR, re.compile(r"(^|[^a-z0-9])flair([^a-z0-9]|$)", re.IGNORECASE)),
        (MRISequence.SWI, re.compile(r"(^|[^a-z0-9])swi([^a-z0-9]|$)", re.IGNORECASE)),
        (MRISequence.MRA, re.compile(r"(^|[^a-z0-9])mra([^a-z0-9]|$)", re.IGNORECASE)),
        (MRISequence.T2W, re.compile(r"(^|[^a-z0-9])t2w?([^a-z0-9]|$)", re.IGNORECASE)),
        (MRISequence.T1W, re.compile(r"(^|[^a-z0-9])t1w?([^a-z0-9]|$)", re.IGNORECASE)),
    ]

    def identify_from_metadata(self, metadata_row: dict[str, Any]) -> MRISequence:
        """Identify sequence from a metadata row by scanning high-signal fields."""
        preferred_keys = (
            "sequence",
            "sequence_type",
            "series_description",
            "protocol_name",
            "modality",
            "filename",
            "path",
        )
        candidates = [metadata_row.get(key) for key in preferred_keys if metadata_row.get(key)]
        if not candidates:
            candidates = [value for value in metadata_row.values() if isinstance(value, str)]
        for candidate in candidates:
            sequence = self.identify_from_filename(str(candidate))
            if sequence is not MRISequence.UNKNOWN:
                return sequence
        return MRISequence.UNKNOWN

    def identify_from_filename(self, filename: str) -> MRISequence:
        """Identify sequence using common filename / series description patterns."""
        normalized = filename.strip()
        for sequence, pattern in self._PATTERNS:
            if pattern.search(normalized):
                return sequence
        return MRISequence.UNKNOWN
