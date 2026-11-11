# connectors/

Integration layer for external clinical systems. Connectors provide standardized access to patient data, imaging services, and authentication — keeping protocol details out of family code.

## Available Connectors

- **`fhir.py`** — FHIR R4 client for patient demographics, encounters, observations, and diagnostic reports.
- **`imaging.py`** — DICOMweb connector for study/series/instance retrieval from PACS and VNA systems.
- **`smart_launcher.py`** — SMART on FHIR OAuth2 PKCE launcher for EHR-embedded authentication.
- **`token_manager.py`** — Token lifecycle management with automatic refresh and expiration handling.

## Framework

- **`base.py`** — `Connector` base class and `ConnectorBundle` abstraction for grouping related connectors.
- **`factory.py`** — Builds connector bundles from `ClinAgentSettings`, wiring up credentials and endpoints automatically.

## Usage Pattern

Families don't instantiate connectors directly. The platform creates a `ConnectorBundle` from settings and passes it to the family at runtime. This keeps connection details centralized and testable.
