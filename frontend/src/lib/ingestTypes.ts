import type { ChatController } from "@/lib/chatTypes"

export type IngestPatientInfo = {
  patient_uid: string
  study_dates: string[]
  timepoints: number
  has_imaging: boolean
  has_reports: boolean
  has_segmentation: boolean
  file_paths: Record<string, string[]>
}

export type IngestProfile = {
  source_path: string
  detected_type: string
  patients: IngestPatientInfo[]
  missing_fields: string[]
  suggested_workflows: string[]
  raw_inventory: Record<string, number>
}

export type IngestTimepoint = {
  date: string
  label: string
  imaging_paths: string[]
  report_text: string | null
  segmentation_path: string | null
  extracted_metrics: Record<string, unknown>
}

export type IngestWorkspace = {
  workspace_id: string
  workflow_type: string
  patient_id: string
  timepoints: IngestTimepoint[]
  metadata: Record<string, unknown>
  created_at: string
}

export type IngestStatus = "idle" | "profiling" | "profiled" | "confirming" | "ready" | "error"

export type IngestController = {
  sourcePath: string
  setSourcePath: (value: string) => void
  profile: IngestProfile | null
  workspace: IngestWorkspace | null
  workspaceId: string | null
  selectedPatientUid: string | null
  setSelectedPatientUid: (value: string | null) => void
  status: IngestStatus
  error: string | null
  profileSource: (sourcePathOverride?: string) => Promise<void>
  profileUpload: (file: File) => Promise<void>
  confirmWorkflow: (workflow: string) => Promise<void>
  clear: () => void
}

export type DemoLayoutContext = {
  chat: ChatController
  ingest: IngestController
}

export type DevLayoutContext = {
  chat: ChatController
}
