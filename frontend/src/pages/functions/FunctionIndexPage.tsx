import { ClipboardCheck, FileCheck } from "lucide-react"

import { ModuleCard } from "@/components/ModuleCard"
import { useApi } from "@/hooks/useApi"

export function FunctionIndexPage() {
  const reportQuality = useApi<{
    cases: { id: string }[]
    workspace: { status_tone?: "urgent" | "alert" | "watch" | "ok" }
  }>("/api/report-quality/workspace")

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ModuleCard
        caseCount={reportQuality.data?.cases.length}
        description="Rendered report QA with grouped findings."
        href="/functions/report-quality"
        icon={FileCheck}
        riskLevel={reportQuality.data?.workspace.status_tone}
        title="Report quality"
      />
      <ModuleCard
        description="Evidence board verifier for drafted claims."
        href="/functions/evidence"
        icon={ClipboardCheck}
        title="Evidence board"
      />
    </div>
  )
}
