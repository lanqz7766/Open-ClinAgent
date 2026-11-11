import { type ChangeEvent, type FormEvent, type KeyboardEvent, type ReactNode, Fragment, useEffect, useMemo, useRef, useState } from "react"
import { ArrowUp, FolderSearch, Paperclip, Send, Trash2 } from "lucide-react"

import { BrandMark } from "@/components/BrandMark"
import { HeroLogoLockup } from "@/components/HeroLogoLockup"
import { IngestProfileCard } from "@/components/IngestProfileCard"
import { MarkdownContent } from "@/components/MarkdownContent"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { RunResultCard } from "@/components/RunResultCard"
import { useApi } from "@/hooks/useApi"
import { useChatStream } from "@/hooks/useChatStream"
import type { ChatController, ChatMessage, ChatRequestConfig } from "@/lib/chatTypes"
import type { IngestController } from "@/lib/ingestTypes"
import type { ChatOptionsSnapshot } from "@/types/api"
import { cn } from "@/lib/utils"

const SUGGESTIONS = [
  {
    label: "Open Neuro MRI Workspace",
    prompt: "Open the Neuro MRI Report Generator and show me a brain MRI study",
  },
  {
    label: "Check Critical Potassium Escalation",
    prompt: "Check if this critical potassium lab needs urgent escalation",
  },
  {
    label: "Review Radiology Report Quality",
    prompt: "Run quality review on this radiology report draft",
  },
]

function linkifySegment(text: string) {
  const parts = text.split(/(https?:\/\/[^\s]+)/g)
  return parts.map((part, index) => {
    if (/^https?:\/\//.test(part)) {
      return (
        <a
          className="break-all text-[hsl(var(--primary))] underline underline-offset-2"
          href={part}
          key={`${part}-${index}`}
          rel="noreferrer"
          target="_blank"
        >
          {part}
        </a>
      )
    }
    return <Fragment key={`${part}-${index}`}>{part}</Fragment>
  })
}

function renderInline(text: string) {
  const tokens = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g).filter(Boolean)
  return tokens.map((token, index) => {
    if (token.startsWith("**") && token.endsWith("**")) {
      return <strong key={`${token}-${index}`}>{linkifySegment(token.slice(2, -2))}</strong>
    }
    if (token.startsWith("*") && token.endsWith("*")) {
      return <em key={`${token}-${index}`}>{linkifySegment(token.slice(1, -1))}</em>
    }
    if (token.startsWith("`") && token.endsWith("`")) {
      return (
        <code
          className="break-all rounded bg-[hsl(var(--muted))] px-1 py-0.5 font-mono text-[11px] text-[hsl(var(--foreground))]"
          key={`${token}-${index}`}
        >
          {token.slice(1, -1)}
        </code>
      )
    }
    return <Fragment key={`${token}-${index}`}>{linkifySegment(token)}</Fragment>
  })
}

function renderRichText(content: string) {
  const lines = content.split("\n")
  const nodes: ReactNode[] = []
  let bulletBuffer: string[] = []

  const flushBullets = () => {
    if (!bulletBuffer.length) {
      return
    }
    nodes.push(
      <ul className="space-y-1 pl-4 text-[13px] leading-6 [overflow-wrap:anywhere]" key={`bullets-${nodes.length}`}>
        {bulletBuffer.map((item, index) => (
          <li className="list-disc text-[hsl(var(--foreground))]" key={`${item}-${index}`}>
            {renderInline(item)}
          </li>
        ))}
      </ul>,
    )
    bulletBuffer = []
  }

  lines.forEach((rawLine, index) => {
    const line = rawLine.trim()
    if (!line) {
      flushBullets()
      return
    }

    if (line.startsWith("- ") || line.startsWith("* ")) {
      bulletBuffer.push(line.slice(2))
      return
    }

    flushBullets()

    if (line.startsWith("### ")) {
      nodes.push(
        <p className="mb-1 mt-3 font-medium text-[hsl(var(--foreground))] [overflow-wrap:anywhere]" key={`heading-${index}`}>
          {renderInline(line.slice(4))}
        </p>,
      )
      return
    }

    nodes.push(
      <p className="text-[13px] leading-6 text-[hsl(var(--foreground))] [overflow-wrap:anywhere]" key={`line-${index}`}>
        {renderInline(line)}
      </p>,
    )
  })

  flushBullets()
  return nodes
}

function isAgentMessage(message: ChatMessage) {
  return message.type === "run_result" || message.role !== "user"
}

function AgentAvatar({ visible }: { visible: boolean }) {
  if (!visible) {
    return <div className="w-8 shrink-0" />
  }

  return (
    <div className="mt-0.5 shrink-0 rounded-2xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--card))] p-1.5 shadow-[0_14px_32px_-24px_rgba(15,23,42,0.18)]">
      <BrandMark compact />
    </div>
  )
}

function EmptyHero({
  onSelect,
}: {
  onSelect: (text: string) => void
}) {
  return (
    <div className="mx-auto flex w-full max-w-[812px] flex-1 flex-col items-center justify-center gap-[14px] px-4 py-[18px] text-center">
      <div>
        <div className="flex justify-center">
          <HeroLogoLockup />
        </div>
      </div>

      <div className="grid w-full max-w-[812px] gap-[8px] md:grid-cols-3">
        {SUGGESTIONS.map((suggestion) => (
          <button
            className="group flex min-h-[70px] min-w-0 flex-col justify-start overflow-hidden rounded-[18px] border border-[hsl(var(--border)/0.42)] bg-transparent px-[15px] py-[12px] text-left transition-colors hover:border-[hsl(var(--border)/0.62)] hover:bg-[hsl(var(--card)/0.22)]"
            key={suggestion.prompt}
            onClick={() => onSelect(suggestion.prompt)}
            type="button"
          >
            <span className="text-[11px] font-medium text-[hsl(var(--muted-foreground))]">Suggested prompt</span>
            <span
              className="mt-[10px] overflow-hidden text-[13px] font-medium leading-[1.4] tracking-[-0.018em] text-[hsl(var(--foreground))] [display:-webkit-box] [-webkit-box-orient:vertical] [-webkit-line-clamp:2] [overflow-wrap:anywhere]"
              style={{ fontFamily: '"Inter Variable", "Inter", system-ui, sans-serif' }}
            >
              {suggestion.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  )
}

function TypingIndicator({ label, showAvatar }: { label: string; showAvatar: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <AgentAvatar visible={showAvatar} />
      <div
        aria-live="polite"
        className="inline-flex items-center rounded-full bg-[hsl(var(--background)/0.9)] px-3 py-2 text-[12px] font-medium text-[hsl(var(--muted-foreground))]"
      >
        {label}
      </div>
    </div>
  )
}

function buildThinkingPhases(latestRoute: ChatController["latestRoute"], toolCalls: ChatController["toolCalls"]) {
  const activeTool = [...toolCalls].reverse().find((call) => call.status === "running")
  const toolLabel = activeTool?.name
    ? activeTool.name.replaceAll("_", " ")
    : null

  if (latestRoute?.needs_clarification) {
    return [
      "Thinking",
      "Matching intent",
      "Choosing workflow",
      "Checking context",
      "Finding the gap",
      "Asking follow-up",
    ]
  }

  return [
    "Thinking",
    "Matching intent",
    "Choosing workflow",
    "Checking context",
    toolLabel ? `Running ${toolLabel}` : "Running tools",
    "Drafting response",
  ]
}

function ThinkingSteps({
  latestError,
  latestRoute,
  streaming,
  toolCalls,
}: {
  latestError: string | null
  latestRoute: ChatController["latestRoute"]
  streaming: boolean
  toolCalls: ChatController["toolCalls"]
}) {
  const [frame, setFrame] = useState(0)

  useEffect(() => {
    if (!streaming) {
      setFrame(0)
      return
    }
    const timer = window.setInterval(() => {
      setFrame((current) => current + 1)
    }, 650)
    return () => window.clearInterval(timer)
  }, [streaming])

  const phases = useMemo(() => buildThinkingPhases(latestRoute, toolCalls), [latestRoute, toolCalls])

  const maxPhaseIndex = latestError
    ? phases.length - 1
    : latestRoute?.needs_clarification
      ? phases.length - 1
      : toolCalls.some((call) => call.status === "running")
        ? 4
        : latestRoute
          ? 3
          : 1

  const activeIndex = Math.max(0, Math.min(maxPhaseIndex, frame))
  const dotSuffix = ".".repeat((frame % 3) + 1)
  const currentPhase = phases[activeIndex] ?? phases[0]

  return (
    <div className="flex items-start gap-3">
      <AgentAvatar visible />
      <div className="min-w-0 rounded-[1.2rem] border border-[hsl(var(--border)/0.68)] bg-[hsl(var(--background)/0.72)] px-4 py-3">
        <p className="text-[12px] font-medium text-[hsl(var(--foreground))]">
          {currentPhase}
          {dotSuffix}
        </p>
      </div>
    </div>
  )
}

function ChatControlSelect({
  ariaLabel,
  className,
  onValueChange,
  options,
  placeholder,
  value,
}: {
  ariaLabel: string
  className?: string
  onValueChange: (value: string) => void
  options: Array<{ label: string; value: string }>
  placeholder: string
  value: string
}) {
  return (
    <div className={cn("min-w-0", className)}>
      <Select onValueChange={onValueChange} value={value}>
        <SelectTrigger
          aria-label={ariaLabel}
          className="h-[26px] min-w-0 rounded-full border-0 bg-transparent px-[8px] text-[12px] text-[hsl(var(--muted-foreground))] shadow-none ring-0 hover:bg-[hsl(var(--background)/0.85)] hover:text-[hsl(var(--foreground))] focus:ring-0 data-[placeholder]:text-[hsl(var(--muted-foreground))]"
        >
          <SelectValue placeholder={placeholder} />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option.value} value={option.value}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function ChatPanel({
  endpoint = "/api/demo/execute-stream",
  className,
  hero = false,
  heroFlat = false,
  controller,
  ingestController,
}: {
  endpoint?: string
  className?: string
  hero?: boolean
  heroFlat?: boolean
  controller?: ChatController
  ingestController?: IngestController
}) {
  const localController = useChatStream({ endpoint })
  const activeController = controller ?? localController
  const { input, setInput, messages, toolCalls, streaming, latestRoute, latestError, sendMessage, clearChat } = activeController
  const chatOptions = useApi<ChatOptionsSnapshot>("/api/chat/options")

  const messagesEndRef = useRef<HTMLDivElement | null>(null)
  const scrollContainerRef = useRef<HTMLDivElement | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const uploadInputRef = useRef<HTMLInputElement | null>(null)
  const [userHasScrolledUp, setUserHasScrolledUp] = useState(false)
  const lastUserMessageCountRef = useRef(0)
  const [showPathInput, setShowPathInput] = useState(false)
  const [selectedModel, setSelectedModel] = useState("")
  const [selectedReasoning, setSelectedReasoning] = useState<"low" | "medium" | "high">("high")

  const visibleMessages = useMemo(
    () => messages.filter((message) => message.type === "run_result" || message.role !== "system"),
    [messages],
  )

  const ingestContext = useMemo(() => {
    const profile = ingestController?.profile
    if (!profile) {
      return undefined
    }
    const patients = Array.isArray(profile.patients) ? profile.patients : []
    const rawInventory = profile.raw_inventory ?? {}
    const hasImaging =
      patients.some((patient) => patient.has_imaging) ||
      Object.entries(rawInventory).some(([extension, count]) => count > 0 && ["nii", "nii.gz", "dcm", "dicom", "zip"].includes(extension))
    const hasSegmentation = patients.some((patient) => patient.has_segmentation)
    const hasLongitudinalData = patients.some((patient) => patient.timepoints > 1)

    return {
      detected_type: profile.detected_type,
      has_imaging: hasImaging,
      has_longitudinal_data: hasLongitudinalData,
      has_segmentation: hasSegmentation,
      patient_count: patients.length,
      raw_inventory: rawInventory,
      source_path: profile.source_path,
      suggested_workflows: profile.suggested_workflows ?? [],
    }
  }, [ingestController?.profile])

  const selectedModelOption = useMemo(
    () => chatOptions.data?.models.find((option) => option.id === selectedModel) ?? null,
    [chatOptions.data?.models, selectedModel],
  )

  const placeholder = useMemo(
    () =>
      streaming
        ? "ClinAgent is thinking…"
        : endpoint === "/api/demo/execute-stream"
          ? "Ask about a clinical case…"
          : endpoint === "/api/dev/execute-stream"
            ? "Inspect a workflow, route, or tool policy…"
            : "Ask a follow-up question…",
    [endpoint, streaming],
  )

  useEffect(() => {
    const options = chatOptions.data
    if (!options) {
      return
    }

    setSelectedModel((current) =>
      current && options.models.some((model) => model.id === current) ? current : options.default_model,
    )

    setSelectedReasoning((current) =>
      options.reasoning_efforts.includes(current) ? current : options.default_reasoning_effort,
    )
  }, [chatOptions.data])

  function scrollToBottom(behavior: ScrollBehavior) {
    const container = scrollContainerRef.current
    if (!container) {
      return
    }
    container.scrollTo({
      top: container.scrollHeight,
      behavior,
    })
  }

  useEffect(() => {
    const userMessageCount = messages.filter((message) => message.type === "text" && message.role === "user").length
    const isNewUserMessage = userMessageCount > lastUserMessageCountRef.current
    lastUserMessageCountRef.current = userMessageCount

    if (isNewUserMessage) {
      scrollToBottom("smooth")
      setUserHasScrolledUp(false)
      return
    }

    if (!userHasScrolledUp) {
      scrollToBottom("auto")
    }
  }, [messages, userHasScrolledUp])

  useEffect(() => {
    const node = textareaRef.current
    if (!node) {
      return
    }
    node.style.height = "0px"
    node.style.height = `${Math.min(node.scrollHeight, hero ? 180 : 140)}px`
  }, [hero, input])

  function handleScroll() {
    const container = scrollContainerRef.current
    if (!container) {
      return
    }
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight
    setUserHasScrolledUp(distanceFromBottom > 80)
  }

  const requestConfig: ChatRequestConfig | undefined =
    selectedModel || ingestContext
      ? {
          ...(ingestContext ? { ingest_context: ingestContext } : {}),
          ...(selectedModel ? { model: selectedModel } : {}),
          ...(selectedModelOption?.supports_reasoning_effort ? { reasoning_effort: selectedReasoning } : {}),
        }
      : undefined

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    void sendMessage(undefined, requestConfig)
  }

  function handleProfilePath() {
    if (!ingestController) {
      return
    }
    void ingestController.profileSource()
  }

  function handleChooseFile() {
    uploadInputRef.current?.click()
  }

  function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]
    if (!file || !ingestController) {
      return
    }
    void ingestController.profileUpload(file)
    event.target.value = ""
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault()
      void sendMessage(undefined, requestConfig)
    }
  }

  function showAvatarForText(index: number) {
    const previous = visibleMessages[index - 1]
    return !previous || !isAgentMessage(previous)
  }

  const showTypingAvatar = !visibleMessages.length || !isAgentMessage(visibleMessages[visibleMessages.length - 1])
  const showHeroEmptyState = hero && !visibleMessages.length && !streaming && !toolCalls.length
  const ingestStatusText =
    ingestController?.status === "profiling"
      ? "Profiling data…"
      : ingestController?.status === "confirming"
        ? "Assembling workspace…"
        : ingestController?.status === "ready"
          ? "Workspace ready."
          : ingestController?.status === "error"
            ? ingestController.error || "Ingest error."
            : ingestController?.status && ingestController.status !== "idle"
              ? "Profile loaded."
              : null
  const streamingStatusText = streaming
    ? ingestController?.status === "profiling" || ingestController?.status === "confirming"
      ? ingestStatusText
      : toolCalls.some((call) => call.status === "running")
        ? "Reviewing…"
        : latestRoute
          ? "Preparing…"
          : latestError
            ? null
            : "Thinking…"
    : null

  return (
    <section
      className={cn(
        "flex h-full min-h-[34rem] flex-col overflow-hidden rounded-[1.75rem] border border-[hsl(var(--border)/0.72)] bg-[hsl(var(--card))] shadow-[0_32px_84px_-48px_rgba(15,23,42,0.22)]",
        hero &&
          "min-h-[653px] rounded-[26px] bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--card)))] shadow-none",
        className,
      )}
    >
      {!hero ? (
        <div className="bg-[linear-gradient(180deg,hsl(var(--card)),hsl(var(--background)/0.82))] px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex min-w-0 items-center gap-2.5 whitespace-nowrap">
                <BrandMark className="shrink-0" compact />
                <p className="min-w-0 truncate text-[15px] font-medium tracking-[-0.03em] text-[hsl(var(--foreground))]">
                  {endpoint === "/api/dev/execute-stream" ? "Chat with Runtime Console" : "Chat with ClinAgent"}
                </p>
              </div>
            </div>
            <button
              aria-label="Clear chat"
              className="inline-flex h-9 items-center gap-2 rounded-full border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--background)/0.72)] px-3 text-[12px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
              onClick={clearChat}
              type="button"
            >
              <Trash2 aria-hidden="true" className="size-3.5" />
              <span>Clear</span>
            </button>
          </div>
        </div>
      ) : null}

      <div
        className={cn(
          "flex-1 overflow-y-auto px-5 py-5",
          showHeroEmptyState
            ? "flex items-center justify-center overflow-hidden px-4 py-[20px] sm:px-[64px]"
            : hero
              ? "space-y-5 bg-[linear-gradient(180deg,hsl(var(--background)/0.18),transparent)]"
              : "space-y-4",
        )}
        onScroll={handleScroll}
        ref={scrollContainerRef}
      >
        {showHeroEmptyState ? (
          <EmptyHero onSelect={(text) => void sendMessage(text, requestConfig)} />
        ) : (
          <div className="space-y-4">
            {hero && visibleMessages.length ? (
              <div className="flex justify-end">
                <button
                  aria-label="Clear chat"
                  className="inline-flex h-9 items-center gap-2 rounded-full border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--background)/0.72)] px-3 text-[12px] text-[hsl(var(--muted-foreground))] transition-colors hover:text-[hsl(var(--foreground))]"
                  onClick={clearChat}
                  type="button"
                >
                  <Trash2 aria-hidden="true" className="size-3.5" />
                  <span>Clear</span>
                </button>
              </div>
            ) : null}

            {ingestController?.profile ? <IngestProfileCard ingest={ingestController} /> : null}

            {visibleMessages.map((message, index) =>
              message.type === "run_result" ? (
                <div className="flex items-start gap-3" key={`artifact-${index}`}>
                  <AgentAvatar visible={showAvatarForText(index)} />
                  <div className="min-w-0 flex-1 pt-1">
                    <RunResultCard
                      allowedAnalyses={message.artifact.allowedAnalyses}
                      availableData={message.artifact.availableData}
                      capabilityStatus={message.artifact.capabilityStatus}
                      claimsSummary={message.artifact.claimsSummary}
                      executionReadiness={message.artifact.executionReadiness}
                      intent={message.artifact.intent}
                      metrics={message.artifact.metrics}
                      missingInputs={message.artifact.missingInputs}
                      onOpenWorkspace={() => undefined}
                      allowedTools={message.artifact.allowedTools}
                      blockedTools={message.artifact.blockedTools}
                      planSummary={message.artifact.planSummary}
                      policyMode={message.artifact.policyMode}
                      qaStatus={message.artifact.qaStatus}
                      recommendedNextAction={message.artifact.recommendedNextAction}
                      reportPreview={message.artifact.reportPreview}
                      riskLevel={message.artifact.riskLevel}
                      subtitle={message.artifact.subtitle}
                      title={message.artifact.title}
                      trendSvg={message.artifact.trendSvg}
                      viewerType={message.artifact.viewerType}
                      workspaceUrl={message.artifact.workspaceUrl}
                    />
                  </div>
                </div>
              ) : message.role === "user" ? (
                <div className="flex justify-end" key={`user-${index}`}>
                  <div className="max-w-[82%] min-w-0 rounded-[1.4rem] rounded-br-md bg-[hsl(var(--primary))] px-4 py-3 text-[13px] leading-6 text-[hsl(var(--primary-foreground))] shadow-[0_18px_40px_-28px_hsl(var(--primary)/0.55)] [overflow-wrap:anywhere]">
                    {renderRichText(message.content)}
                  </div>
                </div>
              ) : (
                <div className="flex items-start gap-3" key={`${message.role}-${index}`}>
                  <AgentAvatar visible={showAvatarForText(index)} />
                  <div className="min-w-0 flex-1 pt-0.5">
                    <div className="min-w-0 rounded-[1.35rem] border border-[hsl(var(--border)/0.68)] bg-[hsl(var(--background)/0.72)] px-4 py-3">
                      <MarkdownContent content={message.content} />
                    </div>
                  </div>
                </div>
              ),
            )}

            {streaming ? (
              <ThinkingSteps
                latestError={latestError}
                latestRoute={latestRoute}
                streaming={streaming}
                toolCalls={toolCalls}
              />
            ) : null}
            {streamingStatusText && (ingestController?.status === "profiling" || ingestController?.status === "confirming") ? (
              <TypingIndicator label={streamingStatusText} showAvatar={showTypingAvatar} />
            ) : null}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <div className={cn("shrink-0 px-5 pb-5", hero ? "px-[31px] pb-[31px] pt-0" : "pt-2")}>
        <form onSubmit={handleSubmit}>
          <input className="hidden" onChange={handleFileChange} ref={uploadInputRef} type="file" />

          <div
            className={cn(
              "rounded-[2rem] border border-[hsl(var(--border)/0.72)] bg-[hsl(var(--background)/0.92)] px-4 py-4 shadow-[0_10px_24px_-16px_rgba(15,23,42,0.18)]",
              hero &&
                "relative min-h-[118px] rounded-[27.3px] bg-[hsl(var(--background)/0.92)] px-[17px] py-[14px] sm:min-h-[100px]",
              hero && !heroFlat && "shadow-[0_12px_28px_-18px_rgba(15,23,42,0.22)]",
              heroFlat && "shadow-none",
            )}
          >
            <textarea
              aria-label="Chat message"
              className={cn(
                "min-w-0 w-full resize-none bg-transparent text-[14px] leading-7 text-[hsl(var(--foreground))] placeholder:text-[hsl(var(--muted-foreground))] focus:outline-none",
                hero ? "max-h-[28px] min-h-[20px] text-[13px] leading-[19.5px]" : "max-h-[140px] min-h-[64px]",
              )}
              disabled={streaming}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              ref={textareaRef}
              rows={1}
              value={input}
            />

            <div
              className={cn(
                "mt-4 flex min-w-0 flex-wrap items-center gap-2",
                hero && "mt-3 items-center gap-2 sm:absolute sm:bottom-[13px] sm:left-[7px] sm:right-[12px] sm:mt-0 sm:flex-nowrap sm:gap-[2px]",
              )}
            >
              <button
                aria-label="Upload file"
                className={cn(
                  "inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--background)/0.88)] hover:text-[hsl(var(--foreground))]",
                  hero && "h-[32.5px] w-[32.5px] px-[9.75px]",
                )}
                onClick={handleChooseFile}
                type="button"
              >
                <Paperclip aria-hidden="true" className={cn("size-4", hero && "size-[13px]")} />
              </button>

              {ingestController ? (
                showPathInput ? (
                  <div
                    className={cn(
                      "flex min-w-0 basis-full items-center gap-2 rounded-full bg-[hsl(var(--background)/0.88)] px-3 py-1.5 sm:min-w-[14rem] sm:flex-1 sm:max-w-[22rem]",
                      hero && "order-last w-full px-[8px] py-1 sm:order-none sm:mx-[2px] sm:h-[26px] sm:max-w-[16rem] sm:py-0",
                    )}
                  >
                    <FolderSearch aria-hidden="true" className="size-3.5 text-[hsl(var(--muted-foreground))]" />
                    <input
                      aria-label="Data path"
                      className="h-8 min-w-0 flex-1 bg-transparent text-[12px] text-[hsl(var(--foreground))] outline-none placeholder:text-[hsl(var(--muted-foreground))]"
                      onChange={(event) => ingestController.setSourcePath(event.target.value)}
                      placeholder="/path/to/longitudinal-data…"
                      value={ingestController.sourcePath}
                    />
                    <button
                      className="inline-flex h-8 items-center justify-center rounded-full bg-[hsl(var(--foreground))] px-3 text-[12px] text-[hsl(var(--background))] transition-opacity hover:opacity-90 disabled:opacity-40"
                      disabled={!ingestController.sourcePath.trim() || ingestController.status === "profiling"}
                      onClick={handleProfilePath}
                      type="button"
                    >
                      Profile
                    </button>
                  </div>
                ) : (
                  <button
                    aria-label="Toggle data path"
                    className="inline-flex h-[26px] items-center gap-[6px] rounded-full px-[8px] text-[12px] leading-none text-[hsl(var(--muted-foreground))] transition-colors hover:bg-[hsl(var(--background)/0.88)] hover:text-[hsl(var(--foreground))]"
                    onClick={() => setShowPathInput(true)}
                    type="button"
                  >
                    <FolderSearch aria-hidden="true" className="size-[11px]" />
                    <span>Path</span>
                  </button>
                )
              ) : null}

              {chatOptions.data ? (
                <>
                  <ChatControlSelect
                    ariaLabel="Select model"
                    className={cn("max-w-[12rem] flex-none", hero && "grow sm:max-w-[8.5rem] sm:grow-0")}
                    onValueChange={setSelectedModel}
                    options={chatOptions.data.models.map((model) => ({ label: model.label, value: model.id }))}
                    placeholder="Model"
                    value={selectedModel}
                  />

                  {!hero && selectedModelOption?.supports_reasoning_effort ? (
                    <ChatControlSelect
                      ariaLabel="Select reasoning effort"
                      className="max-w-[10rem] flex-none"
                      onValueChange={(value) => setSelectedReasoning(value as "low" | "medium" | "high")}
                      options={chatOptions.data.reasoning_efforts.map((effort) => ({
                        label: effort[0].toUpperCase() + effort.slice(1),
                        value: effort,
                      }))}
                      placeholder="Reasoning"
                      value={selectedReasoning}
                    />
                  ) : null}
                </>
              ) : null}

              <div className={cn("ml-auto flex min-w-0 items-center gap-3", hero && "w-full justify-end sm:absolute sm:right-0 sm:top-0 sm:w-auto sm:gap-0")}>
                {!hero && !streaming && ingestStatusText ? (
                  <p aria-live="polite" className="min-w-0 text-[11px] text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
                    {ingestStatusText}
                  </p>
                ) : null}

                <button
                  aria-label="Send message"
                  className={cn(
                    "flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[hsl(var(--foreground))] text-[hsl(var(--background))] transition-opacity hover:opacity-90 disabled:opacity-30",
                    hero &&
                      "h-[42px] w-[42px] rounded-[1.15rem] bg-[hsl(var(--primary)/0.56)] text-[hsl(var(--primary-foreground))] shadow-[0_14px_30px_-18px_hsl(var(--primary)/0.9)] transition-all hover:bg-[hsl(var(--primary)/0.64)] hover:opacity-100 disabled:bg-[hsl(var(--primary)/0.36)] disabled:text-[hsl(var(--primary-foreground)/0.8)] disabled:opacity-100",
                  )}
                  disabled={!input.trim() || streaming}
                  type="submit"
                >
                  {hero ? <Send aria-hidden="true" className="h-[15px] w-[15px]" /> : <ArrowUp aria-hidden="true" className="h-4 w-4" />}
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </section>
  )
}
