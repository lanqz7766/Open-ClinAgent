import { useRef, useState } from "react"
import type { FormEvent } from "react"
import { Navigate } from "react-router-dom"
import { KeyRound } from "lucide-react"
import { BrandWordmark } from "@/components/BrandMark"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/lib/auth"

export function AccountSetupPage() {
  const auth = useAuth()
  const [current, setCurrent] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState("")
  const [saving, setSaving] = useState(false)
  const errorRef = useRef<HTMLParagraphElement>(null)
  const needsConsent = !auth.user?.dua_accepted_at
  if (auth.loading) return <main className="p-6">Loading account...</main>
  if (!auth.user) return <Navigate replace to="/auth" />
  if (!auth.user.account_setup_required) return <Navigate replace to="/demo" />

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError("")
    setSaving(true)
    try {
      if (password !== confirmation) throw new Error("Passwords do not match.")
      await auth.completeSetup(current, password, consent)
      setCurrent("")
      setPassword("")
      setConfirmation("")
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save account.")
      requestAnimationFrame(() => errorRef.current?.focus())
    } finally { setSaving(false) }
  }

  return (
    <main className="min-h-screen bg-background px-5 py-10 text-foreground">
      <div className="mx-auto max-w-md space-y-8">
        <BrandWordmark compact variant="horizontal" />
        <header className="space-y-3 border-b border-border pb-6">
          <KeyRound aria-hidden="true" className="size-6 text-primary" />
          <h1 className="text-2xl font-semibold">Set your password</h1>
          <p className="break-all text-sm text-muted-foreground">{auth.user.email}</p>
        </header>
        <form className="space-y-5" onSubmit={submit}>
          {error && <p ref={errorRef} role="alert" tabIndex={-1} className="rounded-lg border border-destructive/40 p-3 text-sm text-destructive">{error}</p>}
          {[
            { id: "initial-password", label: "Initial password", value: current, change: setCurrent, autoComplete: "current-password", min: 1 },
            { id: "new-password", label: "New password", value: password, change: setPassword, autoComplete: "new-password", min: auth.password_min_length },
            { id: "confirm-password", label: "Confirm new password", value: confirmation, change: setConfirmation, autoComplete: "new-password", min: auth.password_min_length },
          ].map((field) => <div className="space-y-2" key={field.id}>
            <Label htmlFor={field.id}>{field.label}</Label>
            <Input className="h-11" id={field.id} type="password" autoComplete={field.autoComplete} minLength={field.min} maxLength={128} required value={field.value} onChange={(event) => field.change(event.target.value)} />
          </div>)}
          <p className="text-sm text-muted-foreground">At least {auth.password_min_length} characters.</p>
          {needsConsent && <div className="flex items-start gap-3 border-t border-border pt-5">
            <Checkbox id="research-consent" checked={consent} onCheckedChange={(value) => setConsent(value === true)} className="mt-1 shrink-0" />
            <Label htmlFor="research-consent" className="text-sm font-normal leading-6">I agree to use de-identified data for this research preview only. Outputs are not for clinical diagnosis or treatment decisions.</Label>
          </div>}
          <Button className="min-h-11 w-full" type="submit" disabled={saving || (needsConsent && !consent)}>{saving ? "Saving..." : "Continue to workspace"}</Button>
          <Button className="min-h-11 w-full" variant="ghost" type="button" onClick={() => void auth.logout()}>Sign out</Button>
        </form>
      </div>
    </main>
  )
}
