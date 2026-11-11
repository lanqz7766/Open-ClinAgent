import {
  AlertTriangle,
  FileSearch,
  LayoutDashboard,
  ListOrdered,
  SearchCheck,
  ShieldCheck,
} from "lucide-react"

import { ModuleCard } from "@/components/ModuleCard"
import { useApi } from "@/hooks/useApi"
import { withSurfacePath } from "@/lib/surfaces"
import type { ConsoleSnapshot, WorkflowSnapshot } from "@/types/api"

const moduleMeta = {
  findings: { href: withSurfacePath("demo", "/workflows/findings"), icon: FileSearch },
  queue: { href: withSurfacePath("demo", "/workflows/queue"), icon: ListOrdered },
  diagnosis: { href: withSurfacePath("demo", "/workflows/diagnosis"), icon: SearchCheck },
  screening: { href: withSurfacePath("demo", "/workflows/screening"), icon: ShieldCheck },
  safety: { href: withSurfacePath("demo", "/workflows/safety"), icon: AlertTriangle },
  dashboard: { href: withSurfacePath("demo", "/dashboard"), icon: LayoutDashboard },
}

const secondaryModules = new Set([
  "neuro_report",
  "radonc_plan",
  "radonc_plan_optimization",
  "report_quality",
  "evidence",
])

export function WorkflowIndexPage() {
  const consoleSnapshot = useApi<ConsoleSnapshot>("/api/demo/console")
  const findings = useApi<WorkflowSnapshot>("/api/findings/workspace")
  const queue = useApi<WorkflowSnapshot>("/api/queue/workspace")
  const diagnosis = useApi<WorkflowSnapshot>("/api/diagnosis/workspace")
  const screening = useApi<WorkflowSnapshot>("/api/screening/workspace")
  const safety = useApi<WorkflowSnapshot>("/api/safety/workspace")

  const caseCountByModule = {
    findings: findings.data?.cases.length,
    queue: queue.data?.cases.length,
    diagnosis: diagnosis.data?.cases.length,
    screening: screening.data?.cases.length,
    safety: safety.data?.cases.length,
  }

  const modules =
    consoleSnapshot.data?.workflows.filter(
      (workflow) => !secondaryModules.has(workflow.id) && !secondaryModules.has(workflow.module),
    ) ?? []

  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <h1 className="text-[18px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))]">
          Workflows & utilities
        </h1>
        <p className="max-w-2xl text-[13px] leading-6 text-[hsl(var(--muted-foreground))]">
          Operational modules live here so the homepage stays focused on the flagship entry points.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {modules.map((workflow) => {
          const match =
            moduleMeta[workflow.module as keyof typeof moduleMeta] ??
            moduleMeta[workflow.id as keyof typeof moduleMeta]

          if (!match) {
            return null
          }

          const caseCount =
            caseCountByModule[workflow.module as keyof typeof caseCountByModule] ??
            caseCountByModule[workflow.id as keyof typeof caseCountByModule]

          return (
            <ModuleCard
              caseCount={caseCount}
              description={workflow.summary}
              href={match.href}
              icon={match.icon}
              key={workflow.id}
              title={workflow.title}
            />
          )
        })}
      </div>
    </div>
  )
}
