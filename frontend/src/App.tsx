import type { ReactNode } from "react"
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom"

import { DevLayout } from "@/layouts/DevLayout"
import { DemoLayout } from "@/layouts/DemoLayout"
import { useAuth, AuthProvider } from "@/lib/auth"
import { AccountAuditPage } from "@/pages/AccountAuditPage"
import { AccountSetupPage } from "@/pages/AccountSetupPage"
import { AnalysisIndexPage } from "@/pages/analysis/AnalysisIndexPage"
import { BrainTumorPage } from "@/pages/analysis/BrainTumorPage"
import { NeuroKnowledgePage } from "@/pages/analysis/NeuroKnowledgePage"
import { NeuroPage } from "@/pages/analysis/NeuroPage"
import { RadOncPlanPage } from "@/pages/analysis/RadOncPlanPage"
import { NeuroReportPage } from "@/pages/analysis/NeuroReportPage"
import { AuthPage } from "@/pages/AuthPage"
import { DashboardPage } from "@/pages/DashboardPage"
import { DevConsolePage } from "@/pages/DevConsolePage"
import { HomePage } from "@/pages/HomePage"
import { DiagnosisPage } from "@/pages/workflows/DiagnosisPage"
import { FindingsPage } from "@/pages/workflows/FindingsPage"
import { QueuePage } from "@/pages/workflows/QueuePage"
import { SafetyPage } from "@/pages/workflows/SafetyPage"
import { ScreeningPage } from "@/pages/workflows/ScreeningPage"
import { WorkflowIndexPage } from "@/pages/workflows/WorkflowIndexPage"

function RequireAuth({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const location = useLocation()

  if (auth.loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-background text-[13px] text-[hsl(var(--muted-foreground))]">
        Loading account state...
      </div>
    )
  }

  if (auth.auth_required && !auth.user) {
    return <Navigate replace state={{ from: location }} to="/auth" />
  }
  if (auth.user?.account_setup_required) return <Navigate replace to="/auth/setup" />

  return children
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate replace to="/demo" />} />
          <Route path="/auth" element={<AuthPage />} />
          <Route path="/auth/setup" element={<AccountSetupPage />} />

          <Route
            path="/demo"
            element={
              <RequireAuth>
                <DemoLayout />
              </RequireAuth>
            }
          >
            <Route index element={<HomePage />} />
            <Route path="account" element={<AccountAuditPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="workflows" element={<WorkflowIndexPage />} />
            <Route path="workflows/findings" element={<FindingsPage />} />
            <Route path="workflows/queue" element={<QueuePage />} />
            <Route path="workflows/diagnosis" element={<DiagnosisPage />} />
            <Route path="workflows/screening" element={<ScreeningPage />} />
            <Route path="workflows/safety" element={<SafetyPage />} />
            <Route path="analysis" element={<AnalysisIndexPage />} />
            <Route path="analysis/neuro" element={<NeuroPage />} />
            <Route path="analysis/brain-tumor" element={<BrainTumorPage />} />
            <Route path="analysis/neuro-knowledge" element={<NeuroKnowledgePage />} />
            <Route path="analysis/neuro-report" element={<NeuroReportPage />} />
            <Route path="analysis/radonc-plan" element={<RadOncPlanPage />} />
          </Route>

          <Route path="/dev" element={<DevLayout />}>
            <Route index element={<DevConsolePage />} />
          </Route>

          <Route path="*" element={<Navigate replace to="/demo" />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
