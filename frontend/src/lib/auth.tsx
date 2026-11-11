import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react"
import type { ReactNode } from "react"

export type ClinAgentUser = {
  id: string
  email: string
  name: string
  organization: string
  role: string
  status: string
  dua_version: string
  dua_accepted_at: string
  created_at: string
  last_login_at: string | null
  must_change_password: boolean
  account_setup_required: boolean
}

export type AuthAuditEvent = {
  id: string
  action: string
  resource: string
  status: string
  metadata: Record<string, unknown>
  created_at: string
  actor: { email: string; name: string } | null
}

type AuthConfig = {
  auth_required: boolean
  allow_self_registration: boolean
  allow_local_password_reset: boolean
  dua_version: string
  session_days: number
  session_idle_hours: number
  invitation_only: boolean
  email_delivery_configured: boolean
  preview_scope: string
  physician_curated_only: boolean
  public_url: string
  password_min_length: number
}

type AuthResponse = AuthConfig & {
  ok: boolean
  user: ClinAgentUser | null
  error?: string
  message?: string
  reset_token?: string
  reset_url?: string
}

export type LoginPayload = {
  email: string
  password: string
}

export type RegisterPayload = LoginPayload & {
  name: string
  organization: string
  role: string
  dua_accepted: boolean
}

export type InvitationSummary = {
  id: string
  email: string
  name: string
  organization: string
  role: string
  created_at: string
  expires_at: string
}

type AuthContextValue = AuthConfig & {
  user: ClinAgentUser | null
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  login: (payload: LoginPayload) => Promise<void>
  logout: () => Promise<void>
  register: (payload: RegisterPayload) => Promise<void>
  loadInvitation: (token: string) => Promise<InvitationSummary>
  acceptInvitation: (token: string, password: string, duaAccepted: boolean) => Promise<void>
  requestPasswordReset: (email: string) => Promise<AuthResponse>
  resetPassword: (token: string, password: string) => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  completeSetup: (currentPassword: string, newPassword: string, duaAccepted: boolean) => Promise<void>
}

const defaultConfig: AuthConfig = {
  auth_required: false,
  allow_self_registration: true,
  allow_local_password_reset: false,
  dua_version: "clinagent-dua-v1",
  session_days: 7,
  session_idle_hours: 12,
  invitation_only: true,
  email_delivery_configured: false,
  preview_scope: "full",
  physician_curated_only: false,
  public_url: "",
  password_min_length: 12,
}

const AuthContext = createContext<AuthContextValue | null>(null)

async function parseAuthResponse(response: Response): Promise<AuthResponse> {
  const payload = (await response.json()) as AuthResponse
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed with status ${response.status}`)
  }
  return payload
}

async function postAuth(url: string, body?: object): Promise<AuthResponse> {
  const response = await fetch(url, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    credentials: "include",
    body: body ? JSON.stringify(body) : undefined,
  })
  return parseAuthResponse(response)
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<ClinAgentUser | null>(null)
  const [config, setConfig] = useState<AuthConfig>(defaultConfig)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const applyPayload = useCallback((payload: AuthResponse) => {
    setUser(payload.user)
    setConfig({
      auth_required: payload.auth_required,
      allow_self_registration: payload.allow_self_registration,
      allow_local_password_reset: payload.allow_local_password_reset,
      dua_version: payload.dua_version,
      session_days: payload.session_days,
      session_idle_hours: payload.session_idle_hours,
      invitation_only: payload.invitation_only,
      email_delivery_configured: payload.email_delivery_configured,
      preview_scope: payload.preview_scope,
      physician_curated_only: Boolean(payload.physician_curated_only),
      public_url: payload.public_url || "",
      password_min_length: payload.password_min_length || 12,
    })
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch("/api/auth/me", { credentials: "include" })
      applyPayload(await parseAuthResponse(response))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load account state")
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [applyPayload])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const login = useCallback(
    async (payload: LoginPayload) => {
      setError(null)
      applyPayload(await postAuth("/api/auth/login", payload))
    },
    [applyPayload],
  )

  const register = useCallback(
    async (payload: RegisterPayload) => {
      setError(null)
      applyPayload(await postAuth("/api/auth/register", payload))
    },
    [applyPayload],
  )

  const loadInvitation = useCallback(async (token: string) => {
    const response = await fetch(`/api/auth/invitations/${encodeURIComponent(token)}`, { credentials: "include" })
    const payload = (await response.json()) as AuthResponse & { invitation?: InvitationSummary }
    if (!response.ok || !payload.invitation) {
      throw new Error(payload.error || "Invitation is invalid or expired.")
    }
    return payload.invitation
  }, [])

  const acceptInvitation = useCallback(
    async (token: string, password: string, duaAccepted: boolean) => {
      setError(null)
      applyPayload(await postAuth("/api/auth/invitations/accept", {
        token,
        password,
        dua_accepted: duaAccepted,
      }))
    },
    [applyPayload],
  )

  const logout = useCallback(async () => {
    setError(null)
    applyPayload(await postAuth("/api/auth/logout"))
  }, [applyPayload])

  const requestPasswordReset = useCallback(async (email: string) => {
    setError(null)
    return postAuth("/api/auth/password/forgot", { email })
  }, [])

  const resetPassword = useCallback(
    async (token: string, password: string) => {
      setError(null)
      applyPayload(await postAuth("/api/auth/password/reset", { token, password }))
    },
    [applyPayload],
  )

  const changePassword = useCallback(
    async (currentPassword: string, newPassword: string) => {
      setError(null)
      applyPayload(await postAuth("/api/auth/password/change", {
        current_password: currentPassword,
        new_password: newPassword,
      }))
    },
    [applyPayload],
  )

  const completeSetup = useCallback(async (currentPassword: string, newPassword: string, duaAccepted: boolean) => {
    applyPayload(await postAuth("/api/auth/account/setup", {
      current_password: currentPassword, new_password: newPassword, dua_accepted: duaAccepted,
    }))
  }, [applyPayload])

  const value = useMemo<AuthContextValue>(
    () => ({
      ...config,
      user,
      loading,
      error,
      refresh,
      login,
      logout,
      register,
      loadInvitation,
      acceptInvitation,
      requestPasswordReset,
      resetPassword,
      changePassword,
      completeSetup,
    }),
    [acceptInvitation, changePassword, completeSetup, config, error, loadInvitation, loading, login, logout, refresh, register, requestPasswordReset, resetPassword, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider")
  }
  return context
}
