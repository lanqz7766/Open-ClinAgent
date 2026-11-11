import { WorkflowModulePage } from "@/pages/workflows/WorkflowModulePage"

export function QueuePage() {
  return <WorkflowModulePage apiPrefix="/api/queue" title="Queue triage" />
}
