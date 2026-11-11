import type { FormEvent } from "react"
import { useEffect, useMemo, useState } from "react"
import { Navigate, useLocation, useNavigate, useSearchParams } from "react-router-dom"
import { CheckCircle2, LockKeyhole, ShieldCheck } from "lucide-react"

import { BrandWordmark } from "@/components/BrandMark"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"
import type { InvitationSummary } from "@/lib/auth"

type AuthMode = "login" | "register" | "forgot" | "reset" | "invite"

const roleOptions = [
  { value: "radiologist", label: "Radiologist" },
  { value: "resident", label: "Resident or fellow" },
  { value: "researcher", label: "Clinical researcher" },
  { value: "admin", label: "Clinical operations" },
]

function Field({
  autoComplete,
  label,
  name,
  onChange,
  placeholder,
  required = true,
  type = "text",
  value,
}: {
  autoComplete?: string
  label: string
  name: string
  onChange: (value: string) => void
  placeholder?: string
  required?: boolean
  type?: string
  value: string
}) {
  return (
    <div className="space-y-2">
      <Label className="text-[12px] text-[hsl(var(--foreground))]" htmlFor={name}>
        {label}
      </Label>
      <Input
        autoComplete={autoComplete}
        className="h-10 rounded-xl border-[hsl(var(--border)/0.85)] bg-[hsl(var(--background)/0.5)]"
        id={name}
        name={name}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        required={required}
        type={type}
        value={value}
      />
    </div>
  )
}

export function AuthPage() {
  const auth = useAuth()
  const loadInvitation = auth.loadInvitation
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const initialResetToken = searchParams.get("reset_token") || ""
  const initialInviteToken = searchParams.get("invite_token") || ""
  const [mode, setMode] = useState<AuthMode>(initialInviteToken ? "invite" : initialResetToken ? "reset" : "login")
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [resetToken] = useState(initialResetToken)
  const [inviteToken] = useState(initialInviteToken)
  const [invitation, setInvitation] = useState<InvitationSummary | null>(null)
  const [name, setName] = useState("")
  const [organization, setOrganization] = useState("")
  const [role, setRole] = useState("radiologist")
  const [duaAccepted, setDuaAccepted] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [formNotice, setFormNotice] = useState<string | null>(null)

  useEffect(() => {
    if (!inviteToken) return
    let active = true
    loadInvitation(inviteToken)
      .then((value) => {
        if (active) setInvitation(value)
      })
      .catch((err) => {
        if (active) setFormError(err instanceof Error ? err.message : "Invitation is invalid or expired.")
      })
    return () => {
      active = false
    }
  }, [inviteToken, loadInvitation])

  const redirectTo = useMemo(() => {
    const state = location.state as { from?: { pathname?: string; search?: string } } | null
    const pathname = state?.from?.pathname || "/demo"
    const search = state?.from?.search || ""
    return `${pathname}${search}`
  }, [location.state])

  if (!auth.loading && auth.user) {
    return <Navigate replace to={auth.user.account_setup_required ? "/auth/setup" : redirectTo} />
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSubmitting(true)
    setFormError(null)
    try {
      if (mode === "invite") {
        await auth.acceptInvitation(inviteToken, password, duaAccepted)
      } else if (mode === "register") {
        await auth.register({
          email,
          password,
          name,
          organization,
          role,
          dua_accepted: duaAccepted,
        })
      } else if (mode === "forgot") {
        const payload = await auth.requestPasswordReset(email)
        setFormNotice(payload.message || "If an active account exists, reset instructions have been sent.")
        return
      } else if (mode === "reset") {
        await auth.resetPassword(resetToken, password)
      } else {
        await auth.login({ email, password })
      }
      navigate(redirectTo, { replace: true })
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Authentication failed")
    } finally {
      setSubmitting(false)
    }
  }

  const lockedRegistration = mode === "register" && !auth.allow_self_registration
  const resetUnavailable = mode === "forgot" && !auth.email_delivery_configured
  const authModeLabel = "Restricted access"
  const authModeDescription = mode === "invite"
    ? "Complete your invited account to enter the closed physician preview."
    : "Sign in with your ClinAgent account."
  const submitLabel =
    submitting
      ? "Working..."
      : mode === "login"
        ? "Sign in"
        : mode === "register"
          ? "Create account"
          : mode === "invite"
            ? "Accept invitation"
          : mode === "forgot"
            ? "Request reset"
            : "Set new password"

  return (
    <main className="min-h-screen bg-background px-4 py-5 text-foreground sm:px-6 lg:px-8">
      <div className="mx-auto grid min-h-[calc(100vh-2.5rem)] w-full max-w-[1080px] content-center gap-5 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <section className="rounded-[1.6rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card)/0.92)] p-5 shadow-[0_30px_80px_-50px_rgba(15,23,42,0.6)] sm:p-7">
          <div className="mb-8 flex items-start justify-between gap-4">
            <BrandWordmark compact variant="horizontal" />
            <div className="inline-flex items-center gap-2 rounded-full border border-[hsl(var(--border)/0.7)] px-3 py-1 text-[11px] font-medium text-[hsl(var(--muted-foreground))]">
              <LockKeyhole className="size-3.5" />
              {authModeLabel}
            </div>
          </div>

          <div className="mb-6 max-w-[34rem] space-y-2">
            <h1 className="text-[28px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))]">
              Clinical workspace access
            </h1>
            <p className="text-[14px] leading-7 text-[hsl(var(--muted-foreground))]">
              {authModeDescription}
            </p>
          </div>

          {mode !== "invite" && mode !== "reset" ? (
          <div className="mb-5 inline-flex rounded-xl border border-[hsl(var(--border)/0.8)] bg-[hsl(var(--background)/0.55)] p-1">
            {(["login", ...(auth.allow_self_registration ? (["register"] as const) : [])] as const).map((item) => (
              <button
                className={[
                  "rounded-lg px-4 py-2 text-[12px] font-medium transition-colors",
                  mode === item
                    ? "bg-[hsl(var(--foreground))] text-[hsl(var(--background))]"
                    : "text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]",
                ].join(" ")}
                key={item}
                onClick={() => {
                  setMode(item)
                  setFormError(null)
                  setFormNotice(null)
                }}
                type="button"
              >
                {item === "login" ? "Sign in" : "Register"}
              </button>
            ))}
          </div>
          ) : null}

          <form className="grid gap-4" onSubmit={onSubmit}>
            {mode === "invite" && invitation ? (
              <div className="rounded-xl border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--background)/0.45)] px-4 py-3">
                <div className="text-[13px] font-medium text-[hsl(var(--foreground))]">{invitation.name}</div>
                <div className="mt-1 text-[12px] text-[hsl(var(--muted-foreground))]">
                  {invitation.email} · {invitation.organization || "Invited reviewer"}
                </div>
              </div>
            ) : null}

            {mode === "register" ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Field autoComplete="name" label="Full name" name="name" onChange={setName} value={name} />
                <Field
                  autoComplete="organization"
                  label="Institution"
                  name="organization"
                  onChange={setOrganization}
                  placeholder="Hospital or research group"
                  value={organization}
                />
              </div>
            ) : null}

            <div className={mode === "forgot" || mode === "invite" || mode === "reset" ? "grid gap-4" : "grid gap-4 sm:grid-cols-2"}>
              {mode === "invite" || mode === "reset" ? null : (
              <Field
                autoComplete="email"
                label="Email"
                name="email"
                onChange={setEmail}
                placeholder="name@institution.org"
                type="email"
                value={email}
              />
              )}
              {mode === "forgot" ? null : (
                <Field
                  autoComplete={mode === "register" || mode === "invite" || mode === "reset" ? "new-password" : "current-password"}
                  label={mode === "reset" ? "New password" : "Password"}
                  name="password"
                  onChange={setPassword}
                  placeholder={mode === "register" || mode === "invite" || mode === "reset" ? "12–128 characters" : ""}
                  type="password"
                  value={password}
                />
              )}
            </div>

            {mode === "register" || mode === "invite" ? (
              <div className="grid gap-4">
                {mode === "register" ? <div className="space-y-2">
                  <Label className="text-[12px] text-[hsl(var(--foreground))]" htmlFor="role">
                    Clinical role
                  </Label>
                  <select
                    className="h-10 w-full rounded-xl border border-[hsl(var(--border)/0.85)] bg-[hsl(var(--background)/0.5)] px-3 text-[13px] text-[hsl(var(--foreground))] outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring)/0.3)]"
                    id="role"
                    onChange={(event) => setRole(event.target.value)}
                    value={role}
                  >
                    {roleOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </div> : null}

                <label className="flex gap-3 rounded-xl border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--background)/0.45)] p-4 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
                  <Checkbox
                    checked={duaAccepted}
                    className="mt-1"
                    onCheckedChange={(checked) => setDuaAccepted(checked === true)}
                  />
                  <span>
                    I understand this is a research preview, not a diagnostic system. I will upload only
                    de-identified data that I am authorized to use.
                  </span>
                </label>
              </div>
            ) : null}

            {formNotice ? (
              <div className="rounded-xl border border-[hsl(var(--status-ok)/0.35)] bg-[hsl(var(--status-ok)/0.08)] px-3 py-2 text-[12px] text-[hsl(var(--status-ok))]">
                {formNotice}
              </div>
            ) : null}

            {formError || auth.error || lockedRegistration ? (
              <div className="rounded-xl border border-[hsl(var(--destructive)/0.35)] bg-[hsl(var(--destructive)/0.08)] px-3 py-2 text-[12px] text-[hsl(var(--destructive))]">
                {lockedRegistration ? "Self-registration is disabled for this deployment." : formError || auth.error}
              </div>
            ) : null}

            <Button className="h-10 rounded-xl" disabled={submitting || lockedRegistration || resetUnavailable} type="submit">
              {submitLabel}
            </Button>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-[hsl(var(--muted-foreground))]">
              {mode === "login" ? (
                <button
                  className="font-medium text-[hsl(var(--foreground))] hover:underline"
                  onClick={() => {
                    setMode("forgot")
                    setFormError(null)
                    setFormNotice(null)
                  }}
                  type="button"
                >
                  Forgot password
                </button>
              ) : null}
              {mode !== "login" && mode !== "invite" ? (
                <button
                  className="font-medium text-[hsl(var(--foreground))] hover:underline"
                  onClick={() => {
                    setMode("login")
                    setFormError(null)
                    setFormNotice(null)
                  }}
                  type="button"
                >
                  Back to sign in
                </button>
              ) : null}
              {mode === "forgot" && !auth.email_delivery_configured ? (
                <span>Password reset is temporarily unavailable. Contact the preview administrator.</span>
              ) : null}
            </div>
          </form>
        </section>

        <aside className="grid gap-4 content-center">
          <div className="rounded-[1.35rem] border border-[hsl(var(--border)/0.75)] bg-[hsl(var(--card)/0.84)] p-5">
            <div className="mb-4 flex items-center gap-3">
              <div className="grid size-10 place-items-center rounded-xl bg-[hsl(var(--primary)/0.14)] text-[hsl(var(--primary))]">
                <ShieldCheck className="size-5" />
              </div>
              <div>
                <h2 className="text-[15px] font-medium tracking-[-0.03em]">Closed physician preview</h2>
                <p className="text-[12px] text-[hsl(var(--muted-foreground))]">Research use only</p>
              </div>
            </div>
            <div className="space-y-3 text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
              {[
                "Authorized accounts",
                "De-identified imaging only",
                "Account-scoped activity records",
                "Not for clinical diagnosis",
              ].map((item) => (
                <div className="flex items-start gap-2" key={item}>
                  <CheckCircle2 className="mt-0.5 size-4 text-[hsl(var(--status-ok))]" />
                  <span>{item}</span>
                </div>
              ))}
            </div>
          </div>

        </aside>
      </div>
    </main>
  )
}
