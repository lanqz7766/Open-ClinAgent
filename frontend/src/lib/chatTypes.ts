import type { ToolCallItem } from "@/components/ToolCallCard"
import type { RunResultCardProps } from "@/components/RunResultCard"
import type { DeveloperDoneEvent, DeveloperRouteEvent } from "@/types/api"

export type TextMessage = {
  type: "text"
  role: "user" | "assistant" | "system"
  content: string
}

export type ReportArtifact = Omit<RunResultCardProps, "onOpenWorkspace"> & {
  kind?: string
  module?: string
  case_id?: string
}

export type ResultMessage = {
  type: "run_result"
  artifact: ReportArtifact
}

export type ChatMessage = TextMessage | ResultMessage

export type ChatIngestContext = {
  detected_type?: string
  has_imaging?: boolean
  has_longitudinal_data?: boolean
  has_segmentation?: boolean
  patient_count?: number
  raw_inventory?: Record<string, number>
  source_path?: string
  suggested_workflows?: string[]
}

export type ChatRequestConfig = {
  ingest_context?: ChatIngestContext
  model?: string
  reasoning_effort?: "low" | "medium" | "high"
}

export type ChatController = {
  sessionId: string
  input: string
  setInput: (value: string) => void
  messages: ChatMessage[]
  appendMessages: (messages: ChatMessage[]) => void
  toolCalls: ToolCallItem[]
  streaming: boolean
  latestRoute: DeveloperRouteEvent | null
  latestDone: DeveloperDoneEvent | null
  latestError: string | null
  sendMessage: (messageOverride?: string, requestConfig?: ChatRequestConfig) => Promise<void>
  clearChat: () => void
}
