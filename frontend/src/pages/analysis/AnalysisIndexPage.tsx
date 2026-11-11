import { Activity, Brain, Database } from "lucide-react"

import { ModuleCard } from "@/components/ModuleCard"
import { withSurfacePath } from "@/lib/surfaces"

export function AnalysisIndexPage() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      <ModuleCard
        description="Longitudinal neuro review with timeline, trend, evidence, and report."
        href={withSurfacePath("demo", "/analysis/neuro")}
        icon={Brain}
        title="Neuro review"
      />
      <ModuleCard
        description="Glioma segmentation workspace with PACS/DICOM intake, modality confirmation, tumor volumes, QC, and report-ready text."
        href={withSurfacePath("demo", "/analysis/brain-tumor")}
        icon={Brain}
        title="Brain tumor"
      />
      <ModuleCard
        description="MR-RATE cohort explorer with gateway-proxied case summaries, study reports, and indexed asset paths."
        href={withSurfacePath("demo", "/analysis/neuro-knowledge")}
        icon={Database}
        title="Knowledge explorer"
      />
      <ModuleCard
        description="DVH-guided radiation treatment planning workspace with objective trade-offs and auto-optimization."
        href={withSurfacePath("demo", "/analysis/radonc-plan")}
        icon={Activity}
        title="RadOnc plan"
      />
    </div>
  )
}
