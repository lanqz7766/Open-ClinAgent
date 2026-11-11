import type { DevConsoleSnapshot, ExecutionProfileSummary, HealthSnapshot } from "@/types/api"

type ExecutionProfilePanelProps = {
  health?: HealthSnapshot
  snapshot?: DevConsoleSnapshot
  activeProfile: ExecutionProfileSummary | null
}

export function ExecutionProfilePanel({ activeProfile, health, snapshot }: ExecutionProfilePanelProps) {
  return (
    <section className="rounded-[1.25rem] border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="border-b border-[hsl(var(--border))] px-5 py-4">
        <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Route & Policy</p>
        <h2 className="mt-1 text-[16px] font-medium text-[hsl(var(--foreground))]">Execution profile</h2>
      </div>

      <div className="space-y-5 px-5 py-5">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background)/0.6)] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">System status</div>
            <div className="mt-3 space-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
              <p>Global chat: {health?.provider ?? "…"} · {health?.model ?? "…"}</p>
              <p>Chat API: {String(health?.model_capabilities?.api_architecture ?? "…")}</p>
              <p>MRI analysis: {health?.neuro_report_provider ?? "…"} · {health?.neuro_report_model ?? "…"}</p>
              <p>MRI API: {String(health?.neuro_report_model_capabilities?.api_architecture ?? "…")}</p>
              <p>Queued: {snapshot?.lane_status.total_queued ?? 0} · Active tasks: {snapshot?.lane_status.active_tasks ?? 0}</p>
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--background)/0.6)] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Active workflow</div>
            <div className="mt-3">
              <div className="text-[18px] font-medium text-[hsl(var(--foreground))]">
                {activeProfile?.title ?? "No route selected"}
              </div>
              <p className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                {activeProfile
                  ? `Lane ${activeProfile.default_lane} · ${activeProfile.stage_labels.length} declared stages · ${activeProfile.subagents.length} role agents · mode ${activeProfile.policy_mode}`
                  : "Send a message from the developer console to inspect policy and trace detail."}
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Allowed tools</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(activeProfile?.allowed_tools ?? []).map((tool) => (
                <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[12px]" key={tool}>
                  {tool}
                </span>
              ))}
              {!activeProfile?.allowed_tools.length ? (
                <span className="text-[13px] text-[hsl(var(--muted-foreground))]">No workflow selected.</span>
              ) : null}
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Blocked tool classes</div>
            <div className="mt-3 flex flex-wrap gap-2">
              {(activeProfile?.blocked_tools ?? []).map((tool) => (
                <span className="rounded-full border border-[hsl(var(--border))] bg-[hsl(var(--muted))] px-2.5 py-1 text-[12px] text-[hsl(var(--muted-foreground))]" key={tool}>
                  {tool}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Policy mode</div>
            <div className="mt-3 space-y-2 text-[13px] text-[hsl(var(--foreground))]">
              <p>{snapshot?.recent_trace_summary.tool_policy?.mode ?? activeProfile?.policy_mode ?? "No active policy mode"}</p>
              <p className="text-[hsl(var(--muted-foreground))]">
                Goal: {snapshot?.recent_trace_summary.tool_policy?.primary_goal?.replaceAll("_", " ") ?? "Not declared"}
              </p>
              <p className="text-[hsl(var(--muted-foreground))]">
                Bundle source: {snapshot?.recent_trace_summary.tool_policy?.bundle_source ?? "workflow_profile"}
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">MCP registry</div>
            <div className="mt-3 space-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
              {(health?.mcp_servers ?? []).map((server) => (
                <p key={server.server_id}>
                  <span className="font-medium text-[hsl(var(--foreground))]">{server.label}</span> · {server.availability}
                  {server.workflow_families?.length ? ` · ${server.workflow_families.join(", ")}` : ""}
                </p>
              ))}
              {!(health?.mcp_servers ?? []).length ? <p>No MCP servers registered.</p> : null}
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Reviewed planner defaults</div>
            <div className="mt-3 space-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
              <p>Preferred dashboard: {snapshot?.recent_trace_summary.planner_defaults?.preferred_dashboard_profile ?? "None"}</p>
              <p>Autorun examples: {String(snapshot?.recent_trace_summary.planner_defaults?.autorun_examples ?? false)}</p>
              <p>Review lane open: {String(snapshot?.recent_trace_summary.planner_defaults?.review_lane_default_open ?? false)}</p>
              <p>Output style: {snapshot?.recent_trace_summary.planner_defaults?.output_style ?? "structured_clinical"}</p>
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Memory context</div>
            <div className="mt-3 space-y-2 text-[13px] text-[hsl(var(--muted-foreground))]">
              <p>Retrieval order: {(snapshot?.recent_trace_summary.memory_context?.retrieval_order ?? []).join(" → ") || "Not available"}</p>
              <p>Reviewed patterns: {(snapshot?.recent_trace_summary.memory_context?.reviewed_pattern_memory ?? []).length}</p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Subagent roles</div>
            <div className="mt-3 space-y-2">
              {(activeProfile?.subagents ?? []).map((roleId) => {
                const role = snapshot?.subagent_roles.find((candidate) => candidate.role_id === roleId)
                return (
                  <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-2" key={roleId}>
                    <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{role?.title ?? roleId}</div>
                    <div className="mt-1 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">{role?.summary ?? "Declared for this workflow profile."}</div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="rounded-xl border border-[hsl(var(--border))] p-4">
            <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">Output contract</div>
            <div className="mt-3 text-[13px] text-[hsl(var(--muted-foreground))]">
              <p className="font-medium text-[hsl(var(--foreground))]">{activeProfile?.output_contract.kind ?? "No active contract"}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(activeProfile?.output_contract.sections ?? []).map((section) => (
                  <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-[12px]" key={section}>
                    {section}
                  </span>
                ))}
              </div>
              <div className="mt-4 space-y-2">
                {(activeProfile?.task_templates ?? []).map((task) => (
                  <div className="rounded-lg border border-[hsl(var(--border))] px-3 py-2" key={task.id}>
                    <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{task.label}</div>
                    <div className="mt-1 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">{task.summary}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
