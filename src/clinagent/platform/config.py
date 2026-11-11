from __future__ import annotations

import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from clinagent.connectors.smart_launcher import build_smart_launcher_sim_issuer
from clinagent.platform.local_data import (
    LOCAL_UPLOAD_DIR_ENV,
    NEURO_LONGITUDINAL_DATA_ENV,
    NEURO_REPORT_DATA_ENV,
    RADONC_DEMO_ROOT_ENV,
    SKILLS_DIRS_ENV,
)

_loaded = False
_env_file: Path | None = None


def _discover_env_file() -> None:
    global _loaded, _env_file
    if _loaded:
        return
    _loaded = True

    explicit = os.environ.get("CLINAGENT_ENV_FILE")
    cwd = Path.cwd()
    local_env = cwd / ".env"
    parent_env = cwd.parent / ".env"

    if explicit and Path(explicit).exists():
        _env_file = Path(explicit)
    elif local_env.exists():
        _env_file = local_env
    elif parent_env.exists():
        _env_file = parent_env

    if _env_file:
        from dotenv import load_dotenv

        load_dotenv(_env_file, override=True)


class ClinAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="ignore")

    app_name: str = Field(default="ClinAgent", alias="CLINAGENT_APP_NAME")
    environment: str = Field(default="development", alias="CLINAGENT_ENVIRONMENT")
    host: str = Field(default="127.0.0.1", alias="CLINAGENT_HOST")
    port: int = Field(default=8000, alias="CLINAGENT_PORT")
    api_prefix: str = Field(default="/v1", alias="CLINAGENT_API_PREFIX")
    default_model: str = Field(default="gpt-5-mini", alias="CLINAGENT_DEFAULT_MODEL")
    scenario_dir: str = Field(default="scenarios", alias="CLINAGENT_SCENARIO_DIR")
    artifact_dir: str = Field(default=".clinagent/artifacts", alias="CLINAGENT_ARTIFACT_DIR")
    database_path: str = Field(default=".clinagent/state.db", alias="CLINAGENT_DATABASE_PATH")
    neuro_longitudinal_data_root: str = Field(default="", alias=NEURO_LONGITUDINAL_DATA_ENV)
    neuro_report_data_root: str = Field(default="", alias=NEURO_REPORT_DATA_ENV)
    radonc_demo_root: str = Field(default="", alias=RADONC_DEMO_ROOT_ENV)
    skills_dirs: str = Field(default="", alias=SKILLS_DIRS_ENV)
    local_upload_dir: str = Field(default=".clinagent/uploads", alias=LOCAL_UPLOAD_DIR_ENV)
    log_level: str = Field(default="info", alias="CLINAGENT_LOG_LEVEL")
    memory_history_limit: int = Field(default=3, alias="CLINAGENT_MEMORY_HISTORY_LIMIT")
    connector_timeout_s: float = Field(default=15.0, alias="CLINAGENT_CONNECTOR_TIMEOUT_S")
    ehr_connector_mode: str = Field(default="mock", alias="CLINAGENT_EHR_CONNECTOR_MODE")
    imaging_connector_mode: str = Field(default="mock", alias="CLINAGENT_IMAGING_CONNECTOR_MODE")
    fhir_base_url: str = Field(default="", alias="CLINAGENT_FHIR_BASE_URL")
    fhir_access_token: str = Field(default="", alias="CLINAGENT_FHIR_ACCESS_TOKEN")
    fhir_authorize_url: str = Field(default="", alias="CLINAGENT_FHIR_AUTHORIZE_URL")
    fhir_token_url: str = Field(default="", alias="CLINAGENT_FHIR_TOKEN_URL")
    fhir_client_id: str = Field(default="", alias="CLINAGENT_FHIR_CLIENT_ID")
    fhir_client_secret: str = Field(default="", alias="CLINAGENT_FHIR_CLIENT_SECRET")
    fhir_redirect_uri: str = Field(default="", alias="CLINAGENT_FHIR_REDIRECT_URI")
    fhir_scope: str = Field(
        default="launch/patient patient/*.read encounter/*.read openid fhirUser",
        alias="CLINAGENT_FHIR_SCOPE",
    )
    smart_launcher_base_url: str = Field(
        default="",
        alias="CLINAGENT_SMART_LAUNCHER_BASE_URL",
    )
    smart_launcher_fhir_version: str = Field(
        default="r4",
        alias="CLINAGENT_SMART_LAUNCHER_FHIR_VERSION",
    )
    smart_launcher_launch_type: str = Field(
        default="patient-standalone",
        alias="CLINAGENT_SMART_LAUNCHER_LAUNCH_TYPE",
    )
    smart_launcher_patient_id: str = Field(
        default="",
        alias="CLINAGENT_SMART_LAUNCHER_PATIENT_ID",
    )
    smart_launcher_provider_id: str = Field(
        default="",
        alias="CLINAGENT_SMART_LAUNCHER_PROVIDER_ID",
    )
    smart_launcher_encounter_id: str = Field(
        default="AUTO",
        alias="CLINAGENT_SMART_LAUNCHER_ENCOUNTER_ID",
    )
    smart_launcher_skip_login: bool = Field(
        default=True,
        alias="CLINAGENT_SMART_LAUNCHER_SKIP_LOGIN",
    )
    smart_launcher_skip_auth: bool = Field(
        default=True,
        alias="CLINAGENT_SMART_LAUNCHER_SKIP_AUTH",
    )
    smart_launcher_client_type: str = Field(
        default="public",
        alias="CLINAGENT_SMART_LAUNCHER_CLIENT_TYPE",
    )
    smart_launcher_pkce_mode: str = Field(
        default="always",
        alias="CLINAGENT_SMART_LAUNCHER_PKCE_MODE",
    )
    smart_launcher_auto_callback: bool = Field(
        default=True,
        alias="CLINAGENT_SMART_LAUNCHER_AUTO_CALLBACK",
    )
    dicomweb_base_url: str = Field(default="", alias="CLINAGENT_DICOMWEB_BASE_URL")
    dicomweb_access_token: str = Field(default="", alias="CLINAGENT_DICOMWEB_ACCESS_TOKEN")
    ohif_base_url: str = Field(default="", alias="CLINAGENT_OHIF_BASE_URL")
    nnunet_service_url: str = Field(default="", alias="CLINAGENT_NNUNET_SERVICE_URL")
    nnunet_timeout_s: float = Field(default=600.0, alias="CLINAGENT_NNUNET_TIMEOUT_S")
    nnunet_model_id: str = Field(default="", alias="CLINAGENT_NNUNET_MODEL_ID")
    tumor_segmentation_service_url: str = Field(default="", alias="CLINAGENT_TUMOR_SEGMENTATION_SERVICE_URL")
    tumor_segmentation_timeout_s: float = Field(default=900.0, alias="CLINAGENT_TUMOR_SEGMENTATION_TIMEOUT_S")
    tumor_segmentation_model_id: str = Field(default="", alias="CLINAGENT_TUMOR_SEGMENTATION_MODEL_ID")
    tumor_segmentation_api_key: str = Field(default="", alias="CLINAGENT_TUMOR_SEGMENTATION_API_KEY")
    brain_tumor_dicom_roots: str = Field(default="", alias="CLINAGENT_BRAIN_TUMOR_DICOM_ROOTS")
    brain_tumor_dicom_remote_host: str = Field(default="", alias="CLINAGENT_BRAIN_TUMOR_DICOM_REMOTE_HOST")
    brain_tumor_dicom_remote_work_root: str = Field(
        default="/tmp/clinagent-brain-tumor-dicom",
        alias="CLINAGENT_BRAIN_TUMOR_DICOM_REMOTE_WORK_ROOT",
    )
    brain_tumor_dicom_dcm2niix_bin: str = Field(
        default="dcm2niix",
        alias="CLINAGENT_BRAIN_TUMOR_DICOM_DCM2NIIX_BIN",
    )
    brain_tumor_dicom_scan_limit: int = Field(default=5000, alias="CLINAGENT_BRAIN_TUMOR_DICOM_SCAN_LIMIT")
    mr_rate_base_url: str = Field(default="", alias="CLINAGENT_MR_RATE_BASE_URL")
    mr_rate_local_root: str = Field(default="", alias="CLINAGENT_MR_RATE_LOCAL_ROOT")
    gateway_base_url: str = Field(default="http://127.0.0.1:3000", alias="CLINAGENT_GATEWAY_BASE_URL")
    segmentation_tool_remote_host: str = Field(
        default="",
        alias="CLINAGENT_SEGMENTATION_TOOL_REMOTE_HOST",
    )
    segmentation_tool_remote_root: str = Field(
        default="/tmp/clinagent-segmentation",
        alias="CLINAGENT_SEGMENTATION_TOOL_REMOTE_ROOT",
    )
    segmentation_tool_api_key: str = Field(
        default="",
        alias="CLINAGENT_SEGMENTATION_TOOL_API_KEY",
    )
    segmentation_tool_gpu_id: int | None = Field(
        default=None,
        alias="CLINAGENT_SEGMENTATION_TOOL_GPU_ID",
    )


def load_settings() -> ClinAgentSettings:
    _discover_env_file()
    settings = ClinAgentSettings(_env_file=_env_file) if _env_file else ClinAgentSettings()
    if not settings.fhir_base_url and settings.smart_launcher_base_url:
        settings.fhir_base_url = build_smart_launcher_sim_issuer(
            launcher_base_url=settings.smart_launcher_base_url,
            fhir_version=settings.smart_launcher_fhir_version,
            launch_type=settings.smart_launcher_launch_type,
            patient_id=settings.smart_launcher_patient_id,
            provider_id=settings.smart_launcher_provider_id,
            encounter_id=settings.smart_launcher_encounter_id,
            skip_login=settings.smart_launcher_skip_login,
            skip_auth=settings.smart_launcher_skip_auth,
            scope=settings.fhir_scope,
            redirect_uri=settings.fhir_redirect_uri,
            client_id=settings.fhir_client_id,
            client_secret=settings.fhir_client_secret,
            client_type=settings.smart_launcher_client_type,
            pkce=settings.smart_launcher_pkce_mode,
        )
    return settings
