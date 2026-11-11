import { ToolCallCard, type ToolCallItem } from "@/components/ToolCallCard"
import type { DeveloperDoneEvent, DeveloperRouteEvent, RouteStageSummary, RunTraceSummary } from "@/types/api"

type RunTracePanelProps = {
  route: DeveloperRouteEvent | null
  latestDone: DeveloperDoneEvent | null
  latestError: string | null
  toolCalls: ToolCallItem[]
  recentTrace: RunTraceSummary
}

export function RunTracePanel({
  latestDone,
  latestError,
  recentTrace,
  route,
  toolCalls,
}: RunTracePanelProps) {
  const effectiveRoute = route ?? null
  const stages = (effectiveRoute?.stage_summary ?? recentTrace.stages ?? []).filter(
    (stage): stage is RouteStageSummary => typeof stage !== "string",
  )
  const tasks = effectiveRoute?.task_summary ?? recentTrace.tasks ?? []
  const subagentActivity = effectiveRoute?.subagent_activity ?? recentTrace.subagent_activity ?? []
  const finalOutputs = recentTrace.final_outputs ?? []
  const toolPolicy = effectiveRoute?.tool_policy ?? recentTrace.tool_policy ?? {}
  const plannerDefaults = effectiveRoute?.planner_defaults ?? recentTrace.planner_defaults ?? {}
  const memoryContext = effectiveRoute?.memory_context ?? recentTrace.memory_context ?? {}
  const mcpServers = effectiveRoute?.mcp_servers ?? recentTrace.mcp_servers ?? []

  return (
    <section className="rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border))] px-5 py-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Run Trace</p>
        <h2 className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Live developer trace</h2>
      </div>

      <div className="space-y-5 px-5 py-5">
        <div className="rounded-xl border border-[hsl(var(--border))] p-4">
          <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Route explanation</div>
          <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            <p className="font-medium text-[hsl(var(--foreground))]">
              {effectiveRoute?.workflow_id ? `Workflow: ${effectiveRoute.workflow_id}` : "No active route"}
            </p>
            <p>{effectiveRoute?.developer_explanation ?? recentTrace.route?.reason ?? "Send a request to inspect route and policy reasoning."}</p>
            {effectiveRoute?.handoff ? (
              <pre className="overflow-x-auto rounded-lg bg-[hsl(var(--background))] p-3 text-[12px] text-[hsl(var(--muted-foreground))]">
                {JSON.stringify(effectiveRoute.handoff, null, 2)}
              </pre>
            ) : null}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Declared stages</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {stages.map((stage) => (
                <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-2 text-[12px]" key={stage.id}>
                  <div className="font-medium text-[hsl(var(--foreground))]">{stage.label}</div>
                  <div className="mt-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                    {stage.primary_goal ? `Goal ${stage.primary_goal.replaceAll("_", " ")} · ` : null}
                    {stage.policy_mode ?? "pending"}
                  </div>
                </div>
              ))}
              {!stages.length ? <span className="text-[13px] text-[hsl(var(--muted-foreground))]">No active stage plan.</span> : null}
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Task skeleton</div>
            <div className="mt-3 space-y-2">
              {tasks.map((task) => (
                <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-2" key={task.id}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{task.label}</div>
                    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{task.status}</div>
                  </div>
                  <div className="mt-1 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">{task.summary}</div>
                  <div className="mt-2 text-[11px] leading-5 text-[hsl(var(--muted-foreground))]">
                    {task.primary_goal ? `Goal ${task.primary_goal.replaceAll("_", " ")} · ` : null}
                    {task.dashboard_profile ? `Dashboard ${task.dashboard_profile.replaceAll("_", " ")} · ` : null}
                    {task.policy_mode ?? "pending"}
                  </div>
                </div>
              ))}
              {!tasks.length ? <span className="text-[13px] text-[hsl(var(--muted-foreground))]">No task skeleton yet.</span> : null}
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Subagent activity</div>
            <div className="mt-3 space-y-2">
              {subagentActivity.map((item) => (
                <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-2" key={item.role_id}>
                  <div className="flex items-center justify-between gap-3">
                    <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{item.title}</div>
                    <div className="text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">{item.status}</div>
                  </div>
                  <div className="mt-1 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">{item.summary}</div>
                </div>
              ))}
              {!subagentActivity.length ? <span className="text-[13px] text-[hsl(var(--muted-foreground))]">No subagent activity yet.</span> : null}
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Tool policy</div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              <p className="font-medium text-[hsl(var(--foreground))]">{toolPolicy.mode ?? "No policy mode"}</p>
              <p>Primary goal: {toolPolicy.primary_goal?.replaceAll("_", " ") ?? "Not declared"}</p>
              <p>Allowed tools: {(toolPolicy.allowed_tools ?? []).length}</p>
              <p>Blocked tools: {(toolPolicy.blocked_tools ?? []).join(", ") || "None"}</p>
              <p>Blocked classes: {(toolPolicy.blocked_tool_classes ?? []).join(", ") || "None"}</p>
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">MCP context</div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              {mcpServers.map((server) => (
                <p key={server.server_id}>
                  <span className="font-medium text-[hsl(var(--foreground))]">{server.label}</span> · {server.availability}
                  {server.workflow_families?.length ? ` · ${server.workflow_families.join(", ")}` : ""}
                </p>
              ))}
              {!mcpServers.length ? <p>No MCP servers declared.</p> : null}
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Reviewed memory defaults</div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              <p>Preferred dashboard: {plannerDefaults.preferred_dashboard_profile ?? "None"}</p>
              <p>Autorun examples: {String(plannerDefaults.autorun_examples ?? false)}</p>
              <p>Review lane default open: {String(plannerDefaults.review_lane_default_open ?? false)}</p>
              <p>Output style: {plannerDefaults.output_style ?? "structured_clinical"}</p>
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Memory retrieval</div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              <p>Order: {(memoryContext.retrieval_order ?? []).join(" → ") || "Not available"}</p>
              <p>Entity memory: {(memoryContext.entity_memory ?? []).length}</p>
              <p>Workflow memory: {(memoryContext.workflow_memory ?? []).length}</p>
              <p>Reviewed patterns: {(memoryContext.reviewed_pattern_memory ?? []).length}</p>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-[hsl(var(--border))] overflow-hidden">
          <div className="border-b border-[hsl(var(--border))] px-4 py-3 text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">
            Tool activity
          </div>
          <div className="divide-y divide-[hsl(var(--border))]">
            {(toolCalls.length ? toolCalls : recentTrace.tool_calls.map((item, index) => ({
              id: `${item.name}-${index}`,
              name: item.name,
              status: (item.status as ToolCallItem["status"]) ?? "done",
              preview: item.preview,
              error: item.error,
            }))).map((call) => (
              <ToolCallCard key={call.id} {...call} />
            ))}
            {!toolCalls.length && !recentTrace.tool_calls.length ? (
              <div className="px-4 py-4 text-[13px] text-[hsl(var(--muted-foreground))]">No tool activity captured yet.</div>
            ) : null}
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Final output</div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              <p className="font-medium text-[hsl(var(--foreground))]">{latestDone?.status ?? recentTrace.status}</p>
              <p>{latestDone?.result ?? finalOutputs[0]?.summary ?? "No final output yet."}</p>
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Errors</div>
            <div className="mt-3 space-y-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              {latestError ? <p>{latestError}</p> : null}
              {(recentTrace.errors ?? []).map((error) => (
                <p key={error}>{error}</p>
              ))}
              {!latestError && !(recentTrace.errors ?? []).length ? <p>No errors captured.</p> : null}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
