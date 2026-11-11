import type { ToolCallItem } from "@/components/ToolCallCard"
import type { ChatMessage } from "@/lib/chatTypes"
import type { DeveloperDoneEvent, DeveloperRouteEvent } from "@/types/api"

type ChatSnapshot = {
  sessionId: string
  input: string
  messages: ChatMessage[]
  toolCalls: ToolCallItem[]
  streaming: boolean
  latestRoute: DeveloperRouteEvent | null
  latestDone: DeveloperDoneEvent | null
  latestError: string | null
}

function createSessionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID()
  }
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

function emptySnapshot(): ChatSnapshot {
  return {
    sessionId: createSessionId(),
    input: "",
    messages: [],
    toolCalls: [],
    streaming: false,
    latestRoute: null,
    latestDone: null,
    latestError: null,
  }
}

const snapshots = new Map<string, ChatSnapshot>()

let snapshot: ChatSnapshot = emptySnapshot()

function getStoreSnapshot(key = "default") {
  if (key === "default") {
    return snapshot
  }
  return snapshots.get(key) ?? emptySnapshot()
}

function setStoreSnapshot(key: string, next: ChatSnapshot) {
  if (key === "default") {
    snapshot = next
    return
  }
  snapshots.set(key, next)
}

export function getChatSnapshot(key = "default"): ChatSnapshot {
  return getStoreSnapshot(key)
}

export function setChatSnapshot(next: ChatSnapshot, key = "default") {
  setStoreSnapshot(key, next)
}

export function clearChatSnapshot(key = "default") {
  setStoreSnapshot(key, emptySnapshot())
}
