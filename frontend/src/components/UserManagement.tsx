import { useMemo, useRef, useState } from "react"
import type { FormEvent } from "react"
import { Copy, KeyRound, RefreshCw, Search, UserPlus, UserRoundCheck, UserRoundX } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useApi } from "@/hooks/useApi"
import { useAuth } from "@/lib/auth"
import type { ClinAgentUser } from "@/lib/auth"

type Operation = { kind: "create" } | { kind: "password" | "status"; user: ClinAgentUser }

async function manageAccount(path: string, method: string, body: object) {
  const response = await fetch(`/api/auth/admin/users${path}`, {
    method, credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  })
  const result = await response.json()
  if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : result.error || "Unable to update account. Check the form and try again.")
  return result as { user: ClinAgentUser }
}

export function UserManagement() {
  const auth = useAuth()
  const accounts = useApi<{ users: ClinAgentUser[] }>("/api/auth/admin/users")
  const [query, setQuery] = useState("")
  const [operation, setOperation] = useState<Operation | null>(null)
  const [name, setName] = useState("")
  const [email, setEmail] = useState("")
  const [role, setRole] = useState("radiologist")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState("")
  const [notice, setNotice] = useState("")
  const errorRef = useRef<HTMLParagraphElement>(null)
  const users = useMemo(() => (accounts.data?.users || []).filter((user) =>
    `${user.name} ${user.email}`.toLowerCase().includes(query.toLowerCase())), [accounts.data, query])
  const signInUrl = auth.public_url ? `${auth.public_url}/auth` : ""
  const shareReady = signInUrl.startsWith("https://")

  function close() {
    if (saving) return
    setOperation(null)
    setPassword("")
    setConfirmation("")
    setError("")
  }
  function open(value: Operation) {
    setOperation(value)
    setError("")
    setNotice("")
    setName("")
    setEmail("")
    setRole("radiologist")
    setPassword("")
    setConfirmation("")
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!operation) return
    setSaving(true)
    setError("")
    try {
      if (operation.kind !== "status" && password !== confirmation) throw new Error("Passwords do not match.")
      const target = operation.kind === "create" ? email : operation.user.email
      if (operation.kind === "create") await manageAccount("", "POST", { email, name, role, password })
      else if (operation.kind === "password") await manageAccount(`/${operation.user.id}/password`, "POST", { password })
      else await manageAccount(`/${operation.user.id}/status`, "PATCH", { status: operation.user.status === "active" ? "suspended" : "active" })
      setNotice(operation.kind === "create" ? `Account created: ${target}` : `Account updated: ${target}`)
      setOperation(null)
      setPassword("")
      setConfirmation("")
      accounts.refetch()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update account.")
      requestAnimationFrame(() => errorRef.current?.focus())
    } finally { setSaving(false) }
  }

  return (
    <section className="min-w-0 border-y border-border py-6" aria-labelledby="accounts-title">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div><h2 id="accounts-title" className="text-xl font-semibold">User accounts</h2><p className="mt-1 text-sm text-muted-foreground">{accounts.data?.users.length ?? 0} accounts · No automatic expiry</p></div>
        <div className="flex gap-2">
          <Button className="size-11" aria-label="Refresh accounts" title="Refresh accounts" size="icon" variant="outline" disabled={accounts.loading} onClick={accounts.refetch}><RefreshCw className="size-4" /></Button>
          <Button className="min-h-11" onClick={() => open({ kind: "create" })}><UserPlus className="size-4" />Add account</Button>
        </div>
      </header>
      <div className="my-5 flex min-w-0 flex-col items-stretch gap-4 sm:flex-row sm:items-end">
        <div className="min-w-0 flex-1 space-y-2"><Label htmlFor="account-search">Search accounts</Label><div className="relative"><Search aria-hidden="true" className="absolute left-3 top-3.5 size-4 text-muted-foreground" /><Input id="account-search" className="h-11 pl-10" value={query} onChange={(event) => setQuery(event.target.value)} /></div></div>
        <div className="min-w-0 flex-[2] space-y-2"><Label htmlFor="account-address">Sign-in address</Label><div className="flex gap-2"><Input id="account-address" className="h-11 min-w-0" readOnly value={signInUrl || "Not configured"} /><Button className="size-11 shrink-0" aria-label="Copy sign-in address" title={shareReady ? "Copy sign-in address" : "HTTPS address is not configured"} size="icon" variant="outline" disabled={!shareReady} onClick={() => {
          void navigator.clipboard.writeText(signInUrl).then(() => setNotice("Sign-in address copied.")).catch(() => setNotice("Unable to copy. Select the sign-in address manually."))
        }}><Copy className="size-4" /></Button></div></div>
      </div>
      {!shareReady && <p className="mb-4 text-sm text-muted-foreground">External sign-in pending HTTPS configuration.</p>}
      {notice && <p role="status" className="mb-4 text-sm font-medium text-[hsl(var(--status-ok))]">{notice}</p>}
      {accounts.error && <p role="alert" className="py-4 text-sm text-destructive">{accounts.error}</p>}
      {accounts.loading ? <p className="py-8 text-sm text-muted-foreground">Loading accounts...</p> : (
        <div>
          <div className="hidden grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_6.5rem] gap-4 border-b border-border pb-3 text-sm text-muted-foreground md:grid"><span>Account</span><span>Role</span><span>Status</span><span className="text-right">Actions</span></div>
          {users.map((user) => <div key={user.id} className="grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3 border-b border-border py-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_6.5rem] md:gap-4">
            <div className="min-w-0"><p className="break-words text-base font-semibold">{user.name}</p><p className="break-all text-sm text-muted-foreground">{user.email}</p></div>
            <span className="row-start-2 text-sm capitalize text-muted-foreground md:row-auto">{user.role}</span>
            <span className={`row-start-3 text-sm font-medium md:row-auto ${user.status === "suspended" ? "text-destructive" : user.account_setup_required ? "text-muted-foreground" : "text-[hsl(var(--status-ok))]"}`}>{user.status === "suspended" ? "Suspended" : user.account_setup_required ? "First sign-in pending" : "Active"}</span>
            <div className="col-start-2 row-span-3 row-start-1 flex gap-2 md:col-auto md:row-auto md:row-span-1">
              <Button className="size-11" size="icon" variant="ghost" aria-label={`Reset password for ${user.email}`} title="Reset password" disabled={user.role === "admin"} onClick={() => open({ kind: "password", user })}><KeyRound className="size-4" /></Button>
              <Button className="size-11" size="icon" variant="ghost" aria-label={`${user.status === "active" ? "Suspend" : "Enable"} ${user.email}`} title={user.status === "active" ? "Suspend account" : "Enable account"} disabled={user.role === "admin"} onClick={() => open({ kind: "status", user })}>{user.status === "active" ? <UserRoundX className="size-4" /> : <UserRoundCheck className="size-4" />}</Button>
            </div>
          </div>)}
          {!users.length && <p className="py-8 text-sm text-muted-foreground">No matching accounts.</p>}
        </div>
      )}
      <Dialog open={Boolean(operation)} onOpenChange={(value) => { if (!value) close() }}>
        <DialogContent className="max-h-[90dvh] w-[calc(100%-2rem)] max-w-lg overflow-y-auto rounded-lg [&>button]:right-2 [&>button]:top-2 [&>button]:grid [&>button]:size-11 [&>button]:place-items-center">
          <DialogHeader className="pr-8"><DialogTitle>{operation?.kind === "create" ? "Add account" : operation?.kind === "password" ? "Reset password" : operation?.kind === "status" && operation.user.status === "active" ? "Suspend account?" : "Enable account?"}</DialogTitle><DialogDescription className="break-all">{operation?.kind === "create" ? "Permanent account. Password setup is required at first sign-in." : operation?.user.email}</DialogDescription></DialogHeader>
          <form className="space-y-4" onSubmit={save}>
            {error && <p ref={errorRef} tabIndex={-1} role="alert" className="text-sm text-destructive">{error}</p>}
            {operation?.kind === "create" && <>
              <div className="space-y-2"><Label htmlFor="new-account-name">Name</Label><Input id="new-account-name" className="h-11" maxLength={160} required value={name} onChange={(e) => setName(e.target.value)} /></div>
              <div className="space-y-2"><Label htmlFor="new-account-email">Email / login</Label><Input id="new-account-email" className="h-11" type="email" autoComplete="off" maxLength={254} required value={email} onChange={(e) => setEmail(e.target.value)} /></div>
              <div className="space-y-2"><Label htmlFor="new-account-role">Role</Label><select id="new-account-role" className="h-11 w-full rounded-lg border border-input bg-background px-3 text-sm" value={role} onChange={(e) => setRole(e.target.value)}><option value="radiologist">Radiologist</option><option value="resident">Resident</option><option value="researcher">Researcher</option></select></div>
            </>}
            {operation?.kind !== "status" && <>
              <div className="space-y-2"><Label htmlFor="account-initial-password">Initial password</Label><Input id="account-initial-password" className="h-11" type="password" autoComplete="new-password" required minLength={auth.password_min_length} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} /></div>
              <div className="space-y-2"><Label htmlFor="account-confirm-password">Confirm initial password</Label><Input id="account-confirm-password" className="h-11" type="password" autoComplete="new-password" required value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></div>
              <p className="text-sm text-muted-foreground">At least {auth.password_min_length} characters. The user must choose a new password at their next sign-in.</p>
            </>}
            {operation?.kind === "status" && <p className="text-sm leading-6">{operation.user.status === "active" ? "Existing sessions will be signed out. Uploaded cases and reports will be retained." : "The account can sign in again. Previous sessions remain signed out."}</p>}
            <div className="flex justify-end gap-3 pt-2"><Button className="min-h-11" variant="outline" type="button" disabled={saving} onClick={close}>Cancel</Button><Button className="min-h-11" type="submit" disabled={saving}>{saving ? "Saving..." : operation?.kind === "create" ? "Create account" : "Confirm"}</Button></div>
          </form>
        </DialogContent>
      </Dialog>
    </section>
  )
}
