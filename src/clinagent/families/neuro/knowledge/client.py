from __future__ import annotations

from typing import Any

import httpx


class MRRateKnowledgeServiceClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout_s: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if not normalized:
            raise ValueError("CLINAGENT_MR_RATE_BASE_URL is not configured.")
        self.base_url = normalized
        self.timeout_s = timeout_s
        self.transport = transport

    def health(self) -> dict[str, Any]:
        return self._get("/health")

    def get_cohort(self) -> dict[str, Any]:
        return self._get("/cohorts/v1")

    def search(self, query: str) -> dict[str, Any]:
        return self._get("/search", params={"q": query})

    def get_case(self, patient_uid: str) -> dict[str, Any]:
        return self._get(f"/cases/{patient_uid}")

    def get_case_assets(self, patient_uid: str) -> dict[str, Any]:
        return self._get(f"/cases/{patient_uid}/assets")

    def get_study(self, study_uid: str) -> dict[str, Any]:
        return self._get(f"/studies/{study_uid}")

    def create_analysis_launch(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return self._post("/analysis-launches", json_body=payload)

    def get_analysis_launch_manifest(self, launch_id: str) -> dict[str, Any]:
        return self._get(f"/analysis-launches/{launch_id}/manifest")

    def download_analysis_launch_file(self, launch_id: str, file_kind: str) -> bytes:
        return self._get_bytes(f"/analysis-launches/{launch_id}/files/{file_kind}")

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout_s,
            transport=self.transport,
        ) as client:
            response = client.get(path, params=params)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, *, json_body: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(
            base_url=self.base_url,
            timeout=max(self.timeout_s, 300.0),
            transport=self.transport,
        ) as client:
            response = client.post(path, json=json_body)
            response.raise_for_status()
            return response.json()

    def _get_bytes(self, path: str) -> bytes:
        with httpx.Client(
            base_url=self.base_url,
            timeout=max(self.timeout_s, 300.0),
            transport=self.transport,
        ) as client:
            response = client.get(path)
            response.raise_for_status()
            return response.content


class GatewayNeuroKnowledgeClient(MRRateKnowledgeServiceClient):
    def search(self, query: str) -> dict[str, Any]:
        return self._get("/api/neuro-knowledge/search", params={"q": query})

    def health(self) -> dict[str, Any]:
        return self._get("/api/neuro-knowledge/health")

    def get_cohort(self) -> dict[str, Any]:
        return self._get("/api/neuro-knowledge/cohorts/v1")

    def get_case(self, patient_uid: str) -> dict[str, Any]:
        return self._get(f"/api/neuro-knowledge/cases/{patient_uid}")

    def get_case_assets(self, patient_uid: str) -> dict[str, Any]:
        return self._get(f"/api/neuro-knowledge/cases/{patient_uid}/assets")

    def get_study(self, study_uid: str) -> dict[str, Any]:
        return self._get(f"/api/neuro-knowledge/studies/{study_uid}")

    def create_analysis_launch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post("/api/neuro-knowledge/launch", json_body=payload)
