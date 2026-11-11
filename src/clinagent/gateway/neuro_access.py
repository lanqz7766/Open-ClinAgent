from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from clinagent.gateway.auth import ClinAgentAuthStore


def asset_keys(payload: Any) -> list[str]:
    keys: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, str) and value.startswith("/neuro-assets/"):
            keys.add(unquote(urlsplit(value).path))

    visit(payload)
    return sorted(keys)


def public_neuro_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [public_neuro_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            key: public_neuro_payload(item)
            for key, item in value.items()
            if not key.startswith("_") and not key.endswith(("_path", "_dir", "_root"))
            and key not in {"internal_paths", "local_paths"}
        }
    return value


class NeuroAccess:
    def __init__(self, store: ClinAgentAuthStore, curated_patient_ids: set[str]):
        self.store = store
        self.curated_patient_ids = curated_patient_ids

    def patient_allowed(self, patient_id: str) -> bool:
        return not self.store.require_user_auth or patient_id in self.curated_patient_ids

    def session_allowed(self, session_id: str, user_id: str | None) -> bool:
        if not self.store.require_user_auth:
            return True
        access = self.store.get_case_access(case_id=session_id)
        return bool(
            access and access["source"] == "neuro_session" and not access["shared"]
            and self.store.can_access_case(case_id=session_id, user_id=user_id)
        )

    def register_result(self, payload: dict[str, Any], user_id: str | None) -> None:
        if not self.store.require_user_auth:
            return
        if not user_id:
            raise ValueError("An authenticated owner is required.")
        session_id = str(payload["session_id"])
        existing = self.store.get_case_access(case_id=session_id)
        if existing and (existing["shared"] or existing["source"] != "neuro_session"):
            raise ValueError("Session access conflict.")
        self.store.register_case_access(case_id=session_id, owner_user_id=user_id, source="neuro_session")
        self.store.register_case_assets(case_id=session_id, asset_keys=asset_keys(payload))

    def publish_curated(self, patient_id: str, payload: Any) -> Any:
        if self.store.require_user_auth:
            if not self.patient_allowed(patient_id):
                raise ValueError("Patient not available in this preview.")
            case_id = f"neuro-curated:{patient_id}"
            self.store.register_case_access(case_id=case_id, owner_user_id=None, source=case_id, shared=True)
            self.store.register_case_assets(case_id=case_id, asset_keys=asset_keys(payload))
            return public_neuro_payload(payload)
        return payload

    def asset_allowed(self, path: str, user_id: str | None) -> bool:
        return self.store.can_access_asset(
            asset_key=path, user_id=user_id,
            shared_sources={f"neuro-curated:{patient_id}" for patient_id in self.curated_patient_ids},
        )
