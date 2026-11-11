# ClinAgent Frontend

Browser-based workspace for ClinAgent. Provides the interactive UI for clinical workflow execution, imaging review, report generation, and agent trace inspection.

## Stack

- **React 18** + **TypeScript** — component-driven UI
- **Vite** — dev server with HMR
- **Tailwind CSS** — utility-first styling
- **WebSocket** — real-time agent streaming from the gateway

## Key Components

| Component | Purpose |
|-----------|---------|
| `ChatPanel` | Conversational interface with the agent |
| `HybridImagingViewer` | Multi-sequence imaging display |
| `CornerstoneStructuralViewer` | DICOM structural viewer |
| `EvidenceGrid` | Side-by-side evidence review board |
| `AgentStageFlow` | Visual pipeline progress tracker |
| `RunTracePanel` | Agent execution trace inspector |
| `ExecutionProfilePanel` | Tool policy and stage viewer |
| `WorkspacePanel` | Case and workspace management |

## Pages

| Page | Route |
|------|-------|
| `HomePage` | Landing and family selection |
| `DashboardPage` | Run overview and metrics |
| `DevConsolePage` | Developer tools and diagnostics |
| `analysis/` | Clinical analysis workflows |
| `workflows/` | Workflow execution views |

## Development

```bash
cd frontend
npm install
npm run dev        # start dev server on localhost:5173
npm run build      # production build to dist/
```

The frontend connects to the ClinAgent gateway at `http://127.0.0.1:3000` by default. Start the backend first:

```bash
clinagent --serve
```
