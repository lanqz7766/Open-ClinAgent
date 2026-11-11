import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import type { ToolCallItem, ToolCallStatus } from "@/components/ToolCallCard"
import { clearChatSnapshot, getChatSnapshot, setChatSnapshot } from "@/lib/chatStore"
import type { ChatController, ChatMessage, ChatRequestConfig, ReportArtifact, ResultMessage } from "@/lib/chatTypes"
import type { DeveloperDoneEvent, DeveloperRouteEvent } from "@/types/api"

const NEURO_WORKSPACE_PROMPTS = new Set([
  "open the neuro mri report generator and show me a brain mri study",
  "open the neuro mri report generator and show me a brain mri study.",
])

function normalizePrompt(value: string) {
  return value.trim().toLowerCase().replace(/\s+/g, " ")
}

function localShortcutReply(message: string): ResultMessage | null {
  if (NEURO_WORKSPACE_PROMPTS.has(normalizePrompt(message))) {
    return {
      type: "run_result",
      artifact: {
        kind: "neuro_report",
        module: "neuro_report",
        title: "Neuro MRI Report Generator",
        subtitle: "Open the workspace and select a brain MRI study from the patient library.",
        riskLevel: "low",
        metrics: [
          { label: "Workspace", value: "Neuro MRI" },
          { label: "Mode", value: "Patient library" },
          { label: "Ready", value: "Brain MRI study" },
        ],
        reportPreview: "Launch the Neuro MRI workspace to review a brain MRI study, volumetry, and longitudinal context.",
        qaStatus: { privacy: true, terminology: true, completeness: true },
        claimsSummary: "The Neuro MRI workspace is ready to open.",
        planSummary: "Open the workspace, select a patient case, then run the guided MRI analysis flow.",
        intent: "Open Neuro MRI workspace",
        recommendedNextAction: "Open the workspace and choose a patient case.",
        executionReadiness: "ready",
        viewerType: "nifti",
        workspaceUrl: "/demo/analysis/neuro-report?from=home",
      },
    }
  }
  return null
}

function toolPreview(data: Record<string, unknown>) {
  const preview = data.preview
  if (typeof preview === "string" && preview.trim()) {
    return preview
  }
  const output = data.output
  if (typeof output === "string" && output.trim()) {
    return output.split("\n")[0]
  }
  const error = data.error
  if (typeof error === "string" && error.trim()) {
    return error
  }
  return undefined
}

export function useChatStream({
  endpoint = "/api/demo/execute-stream",
  snapshotKey = "default",
  initialInput,
  initialMessages,
  initialToolCalls,
}: {
  endpoint?: string
  snapshotKey?: string
  initialInput?: string
  initialMessages?: ChatMessage[]
  initialToolCalls?: ToolCallItem[]
} = {}): ChatController {
  const initialSnapshotRef = useRef(getChatSnapshot(snapshotKey))
  const [sessionId, setSessionId] = useState(initialSnapshotRef.current.sessionId)
  const [input, setInputState] = useState(initialInput ?? initialSnapshotRef.current.input)
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages ?? initialSnapshotRef.current.messages)
  const [toolCalls, setToolCalls] = useState<ToolCallItem[]>(initialToolCalls ?? initialSnapshotRef.current.toolCalls)
  const [streaming, setStreaming] = useState(initialSnapshotRef.current.streaming)
  const [latestRoute, setLatestRoute] = useState<DeveloperRouteEvent | null>(initialSnapshotRef.current.latestRoute)
  const [latestDone, setLatestDone] = useState<DeveloperDoneEvent | null>(initialSnapshotRef.current.latestDone)
  const [latestError, setLatestError] = useState<string | null>(initialSnapshotRef.current.latestError)
  const toolCallsRef = useRef<ToolCallItem[]>(initialToolCalls ?? initialSnapshotRef.current.toolCalls)
  const pendingMessagesRef = useRef<ChatMessage[]>([])
  const flushRafRef = useRef<number | null>(null)
  const mountedRef = useRef(true)

  useEffect(() => {
    toolCallsRef.current = toolCalls
  }, [toolCalls])

  useEffect(() => {
    setChatSnapshot({
      sessionId,
      input,
      messages,
      toolCalls,
      streaming,
      latestRoute,
      latestDone,
      latestError,
    }, snapshotKey)
  }, [input, latestDone, latestError, latestRoute, messages, sessionId, snapshotKey, streaming, toolCalls])

  useEffect(() => {
    return () => {
      mountedRef.current = false
      if (flushRafRef.current !== null) {
        cancelAnimationFrame(flushRafRef.current)
      }
    }
  }, [])

  const enqueueMessages = useCallback((items: ChatMessage[]) => {
    pendingMessagesRef.current.push(...items)
    if (flushRafRef.current !== null) {
      return
    }
    flushRafRef.current = requestAnimationFrame(() => {
      const batch = pendingMessagesRef.current
      pendingMessagesRef.current = []
      flushRafRef.current = null
      if (!batch.length || !mountedRef.current) {
        return
      }
      setMessages((current) => [...current, ...batch])
    })
  }, [])

  const clearChat = useCallback(() => {
    clearChatSnapshot(snapshotKey)
    setSessionId(getChatSnapshot(snapshotKey).sessionId)
    setInputState("")
    setMessages([])
    setToolCalls([])
    setStreaming(false)
    setLatestRoute(null)
    setLatestDone(null)
    setLatestError(null)
  }, [snapshotKey])

  const appendMessages = useCallback(
    (items: ChatMessage[]) => {
      if (!items.length) {
        return
      }
      enqueueMessages(items)
    },
    [enqueueMessages],
  )

  const sendMessage = useCallback(
    async (messageOverride?: string, requestConfig?: ChatRequestConfig) => {
      const message = (messageOverride ?? input).trim()
      if (!message || streaming) {
        return
      }

      const shortcutReply = endpoint === "/api/demo/execute-stream" ? localShortcutReply(message) : null
      if (shortcutReply) {
        enqueueMessages([
          { type: "text", role: "user", content: message },
          shortcutReply,
        ])
        setInputState("")
        setToolCalls([])
        setLatestRoute(null)
        setLatestDone(null)
        setLatestError(null)
        return
      }

      enqueueMessages([{ type: "text", role: "user", content: message }])
      setInputState("")
      setStreaming(true)
      setToolCalls([])
      setLatestRoute(null)
      setLatestDone(null)
      setLatestError(null)

      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: sessionId,
            message,
            ...(requestConfig?.ingest_context ? { ingest_context: requestConfig.ingest_context } : {}),
            ...(requestConfig?.model ? { model: requestConfig.model } : {}),
            ...(requestConfig?.reasoning_effort ? { reasoning_effort: requestConfig.reasoning_effort } : {}),
          }),
        })

        if (!response.ok) {
          let detail = `Request failed with status ${response.status}`
          try {
            const payload = (await response.json()) as { error?: string }
            if (payload.error) {
              detail = payload.error
            }
          } catch {
            // Ignore malformed error payloads and keep the generic status text.
          }
          throw new Error(detail)
        }

        if (!response.body) {
          throw new Error(`Request failed with status ${response.status}`)
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ""

        while (true) {
          const { done, value } = await reader.read()
          if (done) {
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const chunks = buffer.split("\n\n")
          buffer = chunks.pop() ?? ""

          for (const chunk of chunks) {
            const lines = chunk.split("\n")
            const eventLine = lines.find((line) => line.startsWith("event: "))
            const dataLine = lines.find((line) => line.startsWith("data: "))

            if (!eventLine || !dataLine) {
              continue
            }

            const eventName = eventLine.slice(7).trim()
            const payload = JSON.parse(dataLine.slice(6)) as Record<string, unknown>

            if (eventName === "routed") {
              setLatestRoute(payload as DeveloperRouteEvent)
            }

            if (eventName === "agent") {
              const kind = String(payload.kind ?? "")
              const data = ((payload.data ?? {}) as Record<string, unknown>) || {}

              if (kind === "tool_call") {
                const toolName = String(data.name ?? "tool")
                setToolCalls((current) => [
                  ...current,
                  {
                    id: `${toolName}-${current.length}-${Date.now()}`,
                    name: toolName,
                    status: "running",
                    preview: toolPreview(data),
                    durationMs: undefined,
                    startedAt: Date.now(),
                  },
                ])
                continue
              }

              if (kind === "tool_result") {
                const toolName = String(data.name ?? "tool")
                const status: ToolCallStatus = data.success === false ? "error" : "done"
                setToolCalls((current) => {
                  const index = [...current]
                    .map((item, itemIndex) => ({ item, itemIndex }))
                    .reverse()
                    .find(({ item }) => item.name === toolName && item.status === "running")?.itemIndex

                  if (index == null) {
                    return [
                      ...current,
                      {
                        id: `${toolName}-${current.length}-${Date.now()}`,
                        name: toolName,
                        status,
                        preview: toolPreview(data),
                        error: typeof data.error === "string" ? data.error : undefined,
                      },
                    ]
                  }

                  const next = [...current]
                  const started = next[index]
                  next[index] = {
                    ...started,
                    status,
                    preview: toolPreview(data),
                    error: typeof data.error === "string" ? data.error : undefined,
                    durationMs: started.startedAt ? Date.now() - started.startedAt : started.durationMs,
                  }
                  return next
                })
              }
            }

            if (eventName === "done" && payload.artifact && typeof payload.artifact === "object") {
              const artifact = payload.artifact as ReportArtifact
              enqueueMessages([{ type: "run_result", artifact }])
              const shouldAutoOpen =
                endpoint === "/api/demo/execute-stream" &&
                (artifact.kind === "neuro_report" || artifact.kind === "radonc_plan") &&
                typeof artifact.workspaceUrl === "string" &&
                artifact.workspaceUrl.includes("autorun=1")
              if (shouldAutoOpen && typeof window !== "undefined") {
                window.setTimeout(() => {
                  window.location.assign(artifact.workspaceUrl)
                }, 500)
              }
            }

            if (eventName === "done") {
              setLatestDone(payload as DeveloperDoneEvent)
              const result = typeof payload.result === "string" ? payload.result.trim() : ""
              if (result) {
                enqueueMessages([
                  {
                    type: "text",
                    role: "assistant",
                    content: result,
                  },
                ])
              }
            }

            if (eventName === "error") {
              const errorText = String(payload.error ?? "Unknown error")
              setLatestError(errorText)
              enqueueMessages([
                {
                  type: "text",
                  role: "assistant",
                  content: errorText,
                },
              ])
            }
          }
        }
      } catch (error) {
        setLatestError(error instanceof Error ? error.message : "Streaming failed.")
        enqueueMessages([
          {
            type: "text",
            role: "assistant",
            content: error instanceof Error ? error.message : "Streaming failed.",
          },
        ])
      } finally {
        if (mountedRef.current) {
          setStreaming(false)
        }
      }
    },
    [endpoint, enqueueMessages, input, sessionId, streaming],
  )

  return useMemo(
    () => ({
      sessionId,
      input,
      setInput: setInputState,
      messages,
      appendMessages,
      toolCalls,
      streaming,
      latestRoute,
      latestDone,
      latestError,
      sendMessage,
      clearChat,
    }),
    [appendMessages, clearChat, input, latestDone, latestError, latestRoute, messages, sendMessage, sessionId, streaming, toolCalls],
  )
}
