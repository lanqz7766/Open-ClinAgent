import type { FormEvent } from "react"
import { useMemo, useState } from "react"
import { Download, FileUp, History, KeyRound, LogIn, RefreshCw, ShieldCheck, TerminalSquare } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useApi } from "@/hooks/useApi"
import type { AuthAuditEvent } from "@/lib/auth"
import { useAuth } from "@/lib/auth"
import { UserManagement } from "@/components/UserManagement"

type AuditResponse = {
  ok: boolean
  events: AuthAuditEvent[]
}

const actionLabels: Record<string, string> = {
  account_registered: "Account registered",
  agent_invocation: "Agent invocation",
  clinical_review: "Clinical review",
  data_export: "Data export",
  data_intake: "Data intake",
  explanation_request: "Explanation request",
  login_succeeded: "Login",
  logout: "Logout",
  password_changed: "Password changed",
  password_change_failed: "Password change failed",
  password_reset_completed: "Password reset completed",
  password_reset_requested: "Password reset requested",
  workflow_action: "Workspace action",
  workflow_rerun: "Workflow rerun",
}

function AuditIcon({ action }: { action: string }) {
  const className = "size-4"
  if (action === "data_export") return <Download className={className} />
  if (action === "data_intake") return <FileUp className={className} />
  if (action === "agent_invocation") return <TerminalSquare className={className} />
  if (action.startsWith("password_")) return <KeyRound className={className} />
  if (action === "login_succeeded" || action === "account_registered") return <LogIn className={className} />
  return <History className={className} />
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date)
}

export function AccountAuditPage() {
  const auth = useAuth()
  const audit = useApi<AuditResponse>("/api/auth/audit/recent?limit=80")
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [passwordStatus, setPasswordStatus] = useState<string | null>(null)
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [savingPassword, setSavingPassword] = useState(false)
  const userInitials = useMemo(() => {
    const name = auth.user?.name || auth.user?.email || ""
    return name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("")
  }, [auth.user?.email, auth.user?.name])

  async function onChangePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSavingPassword(true)
    setPasswordStatus(null)
    setPasswordError(null)
    try {
      await auth.changePassword(currentPassword, newPassword)
      setCurrentPassword("")
      setNewPassword("")
      setPasswordStatus("Password changed. Other active sessions were revoked.")
      audit.refetch()
    } catch (err) {
      setPasswordError(err instanceof Error ? err.message : "Unable to change password")
    } finally {
      setSavingPassword(false)
    }
  }

  return (
    <div className="space-y-5">
      {auth.user?.role === "admin" && <UserManagement />}
      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="rounded-[1.35rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card))] p-5">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div className="space-y-1">
              <h1 className="text-[20px] font-medium">My account</h1>
              <p className="max-w-2xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                Account active. No automatic expiry.
              </p>
            </div>
            <Button onClick={audit.refetch} size="icon" variant="outline" aria-label="Refresh activity" title="Refresh activity">
              <RefreshCw className="size-3.5" />
            </Button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {[
              ["Name", auth.user?.name || "Signed in"],
              ["Email", auth.user?.email || "Unknown"],
              ["Role", auth.user?.role || "Unknown"],
              ["Institution", auth.user?.organization || "Not provided"],
            ].map(([label, value]) => (
              <div className="rounded-xl border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--background)/0.45)] p-3" key={label}>
                <div className="text-[11px] uppercase tracking-[0.16em] text-[hsl(var(--muted-foreground))]">{label}</div>
                <div className="mt-2 truncate text-[13px] font-medium text-[hsl(var(--foreground))]">{value}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-[1.35rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card))] p-5">
          <div className="mb-4 flex items-center gap-3">
            <div className="grid size-10 place-items-center rounded-xl bg-[hsl(var(--primary)/0.14)] text-[hsl(var(--primary))]">
              {userInitials || <ShieldCheck className="size-5" />}
            </div>
            <div>
              <div className="text-[13px] font-medium">DUA accepted</div>
              <div className="text-[12px] text-[hsl(var(--muted-foreground))]">{auth.user?.dua_version}</div>
            </div>
          </div>
          <p className="text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            {auth.user?.dua_accepted_at ? formatDate(auth.user.dua_accepted_at) : "No acceptance timestamp found."}
          </p>
        </div>
      </section>

      <section className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="rounded-[1.35rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card))] p-5">
          <div className="mb-4 flex items-start gap-3">
            <div className="grid size-10 shrink-0 place-items-center rounded-xl bg-[hsl(var(--primary)/0.14)] text-[hsl(var(--primary))]">
              <KeyRound className="size-5" />
            </div>
            <div>
              <h2 className="text-[15px] font-medium tracking-[-0.03em]">Change password</h2>
              <p className="mt-1 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                Other active sessions will be signed out.
              </p>
            </div>
          </div>

          <form className="grid gap-4 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]" onSubmit={onChangePassword}>
            <div className="space-y-2">
              <Label className="text-[12px]" htmlFor="current-password">
                Current password
              </Label>
              <Input
                autoComplete="current-password"
                className="h-10 rounded-xl"
                id="current-password"
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
                type="password"
                value={currentPassword}
              />
            </div>
            <div className="space-y-2">
              <Label className="text-[12px]" htmlFor="new-password">
                New password
              </Label>
              <Input
                autoComplete="new-password"
                className="h-10 rounded-xl"
                id="new-password"
                minLength={auth.password_min_length}
                onChange={(event) => setNewPassword(event.target.value)}
                placeholder={`At least ${auth.password_min_length} characters`}
                required
                type="password"
                value={newPassword}
              />
            </div>
            <Button className="mt-0 h-10 self-end rounded-xl sm:mt-6" disabled={savingPassword} type="submit">
              {savingPassword ? "Saving..." : "Save"}
            </Button>
          </form>
          {passwordStatus ? (
            <div className="mt-4 rounded-xl border border-[hsl(var(--status-ok)/0.35)] bg-[hsl(var(--status-ok)/0.08)] px-3 py-2 text-[12px] text-[hsl(var(--status-ok))]">
              {passwordStatus}
            </div>
          ) : null}
          {passwordError ? (
            <div className="mt-4 rounded-xl border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.08)] px-3 py-2 text-[12px] text-[hsl(var(--destructive))]">
              {passwordError}
            </div>
          ) : null}
        </div>

        <div className="rounded-[1.35rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card))] p-5">
          <div className="text-[13px] font-medium">Sign-in sessions</div>
          <p className="mt-2 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
            Sign in again after {auth.session_idle_hours} hours of inactivity or {auth.session_days} days.
            Your account and password do not expire when a session ends.
          </p>
        </div>
      </section>

      <section className="overflow-hidden rounded-[1.35rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card))]">
        <div className="border-b border-[hsl(var(--border)/0.7)] px-5 py-4">
          <h2 className="text-[15px] font-medium tracking-[-0.03em]">Recent activity</h2>
        </div>
        {audit.loading ? (
          <div className="px-5 py-8 text-[13px] text-[hsl(var(--muted-foreground))]">Loading audit events...</div>
        ) : audit.error ? (
          <div className="px-5 py-8 text-[13px] text-[hsl(var(--destructive))]">{audit.error}</div>
        ) : (
          <div className="divide-y divide-[hsl(var(--border)/0.65)]">
            {(audit.data?.events ?? []).map((event) => (
              <div className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_11rem_7rem]" key={event.id}>
                <div className="flex min-w-0 items-start gap-3">
                  <div className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl bg-[hsl(var(--background)/0.75)] text-[hsl(var(--muted-foreground))]">
                    <AuditIcon action={event.action} />
                  </div>
                  <div className="min-w-0">
                    <div className="truncate text-[13px] font-medium text-[hsl(var(--foreground))]">
                      {actionLabels[event.action] || event.action}
                    </div>
                    <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                      Resource: {event.resource}
                    </div>
                  </div>
                </div>
                <div className="text-[12px] text-[hsl(var(--muted-foreground))]">{formatDate(event.created_at)}</div>
                <div className="text-[12px] font-medium text-[hsl(var(--foreground))]">HTTP {event.status}</div>
              </div>
            ))}
            {!audit.data?.events?.length ? (
              <div className="px-5 py-8 text-[13px] text-[hsl(var(--muted-foreground))]">No audit events yet.</div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  )
}
