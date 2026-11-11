# gateway/

HTTP and WebSocket API server. This is the entry point for the browser UI and any external client that needs to interact with ClinAgent.

## Components

- **`server.py`** — FastAPI application with clinical endpoints, CORS configuration, and static file serving. Mounts all family-specific API routes.
- **`ws.py`** — WebSocket handler for real-time agent streaming. Clients receive step-by-step reasoning, tool calls, and results as the agent works.
- **`protocol.py`** — Shared message types and protocol definitions for gateway communication.
- **`api/ingest.py`** — Data ingestion endpoints for uploading DICOM, NIfTI, and clinical documents.

## Key Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Service health check |
| `WS` | `/ws` | Agent streaming via WebSocket |
| `POST` | `/api/ingest/*` | Data upload and ingestion |
| `GET` | `/demo` | Browser UI entry point |
