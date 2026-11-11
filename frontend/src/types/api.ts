export type RiskTier = "urgent" | "alert" | "watch" | "ok"

export type ConsoleWorkflow = {
  id: string
  title: string
  module: string
  summary: string
  workflow_family?: string
  workflow_task_id?: string
  tags?: string[]
  examples?: string[]
}

export type FamilyRegistryEntry = {
  family_id: string
  display_name: string
  family_type: string
  summary: string
  supported_workflows: string[]
  default_workspace_shell: string
  default_viewer_policy: string
  allowed_mcp_servers: string[]
  review_lane_enabled: boolean
  flagship?: boolean
}

export type WorkflowRegistryEntry = {
  workflow_id: string
  runtime_workflow_id?: string | null
  workflow_family: string
  display_name: string
  summary: string
  intent_patterns: string[]
  intake_schema: string[]
  capability_evaluator: string
  planner_outputs: string[]
  runtime_stages: string[]
  tool_bundle: string[]
  dashboard_profile: string
  report_contract: Record<string, unknown>
  executable: boolean
  review_lane_role?: string
  advisory_skills?: string[]
}

export type ConsoleSnapshot = {
  title: string
  tagline: string
  quick_prompts: string[]
  workflows: ConsoleWorkflow[]
  workflow_families?: FamilyRegistryEntry[]
  workflow_registry?: WorkflowRegistryEntry[]
  highlights?: SummaryCard[]
  modules?: Record<string, { title: string; summary: string; risk: string; default_case_id: string }>
}

export type ExecutionProfileSummary = {
  workflow_id: string
  title: string
  workflow_family?: string
  allowed_tools: string[]
  blocked_tools: string[]
  default_lane: string
  subagents: string[]
  requires_confirmation: boolean
  policy_mode: string
  output_contract: {
    kind: string
    sections?: string[]
  }
  ui_capabilities: Record<string, unknown>
  stage_labels: string[]
  task_templates?: Array<{ id: string; label: string; stage_id: string; role_id?: string; summary: string }>
}

export type DeveloperActionSummary = {
  id: string
  label: string
  description: string
}

export type RouteAlternative = {
  module: string
  title?: string
}

export type RouteStageSummary = {
  id: string
  label: string
  status: string
  workflow_family?: string
  primary_goal?: string
  dashboard_profile?: string
  policy_mode?: string
  allowed_tools?: string[]
  blocked_tools?: string[]
  context_sources?: string[]
  fallback_reason?: string
  summary?: string
}

export type SubagentRoleSummary = {
  role_id: string
  title: string
  summary: string
  activation_condition: string
  output_contract: string
  allowed_tools: string[]
}

export type ToolTraceSummary = {
  name: string
  status: string
  preview?: string
  error?: string
}

export type RunTraceSummary = {
  status: string
  lane?: string
  message?: string
  route?: {
    workflow_id: string
    workflow_family?: string
    workflow_title: string
    target_module: string
    suggested_module?: string | null
    confidence?: number
    fallback?: boolean
    reason?: string
    next_action?: string
    alternatives?: RouteAlternative[]
  }
  profile?: ExecutionProfileSummary
  handoff?: Record<string, unknown>
  stages?: RouteStageSummary[]
  tasks?: Array<{ id: string; label: string; status: string; stage_id: string; summary: string; role_id?: string; family?: string; track?: string; primary_goal?: string; dashboard_profile?: string; policy_mode?: string; allowed_tools?: string[]; blocked_tools?: string[]; context_sources?: string[]; fallback_reason?: string }>
  tool_policy?: { mode?: string; allowed_tools?: string[]; blocked_tools?: string[]; blocked_tool_classes?: string[]; workflow_family?: string; primary_goal?: string; bundle_source?: string }
  mcp_servers?: Array<{ server_id: string; label: string; availability: string; workflows: string[]; workflow_families?: string[]; tool_names?: string[]; health_status?: string }>
  mcp_snapshot?: { workflow_family?: string; workflow_id?: string; tool_names?: string[]; availability?: string; servers?: Array<{ server_id: string; label: string; availability: string }> }
  memory_context?: { retrieval_order?: string[]; entity_memory?: unknown[]; workflow_memory?: unknown[]; user_memory?: unknown; session_memory?: unknown; reviewed_pattern_memory?: unknown[] }
  planner_defaults?: { preferred_dashboard_profile?: string; autorun_examples?: boolean; review_lane_default_open?: boolean; output_style?: string }
  subagent_activity?: Array<{ role_id: string; title: string; status: string; summary: string }>
  tool_calls: ToolTraceSummary[]
  errors: string[]
  final_outputs?: Array<{ kind: string; summary: string }>
}

export type DeveloperRouteEvent = {
  workflow_id: string
  workflow_family?: string
  target_module: string
  suggested_module?: string | null
  confidence?: number
  reason?: string
  next_action?: string
  alternatives?: RouteAlternative[]
  fallback?: boolean
  profile?: ExecutionProfileSummary
  handoff?: Record<string, unknown>
  stage_summary?: Array<RouteStageSummary | string>
  task_summary?: Array<{ id: string; label: string; status: string; stage_id: string; summary: string; role_id?: string; family?: string; track?: string; primary_goal?: string; dashboard_profile?: string; policy_mode?: string; allowed_tools?: string[]; blocked_tools?: string[]; context_sources?: string[]; fallback_reason?: string }>
  tool_policy?: { mode?: string; allowed_tools?: string[]; blocked_tools?: string[]; blocked_tool_classes?: string[]; workflow_family?: string; primary_goal?: string; bundle_source?: string }
  mcp_servers?: Array<{ server_id: string; label: string; availability: string; workflows: string[]; workflow_families?: string[]; tool_names?: string[]; health_status?: string }>
  mcp_snapshot?: { workflow_family?: string; workflow_id?: string; tool_names?: string[]; availability?: string; servers?: Array<{ server_id: string; label: string; availability: string }> }
  memory_context?: { retrieval_order?: string[]; entity_memory?: unknown[]; workflow_memory?: unknown[]; user_memory?: unknown; session_memory?: unknown; reviewed_pattern_memory?: unknown[] }
  planner_defaults?: { preferred_dashboard_profile?: string; autorun_examples?: boolean; review_lane_default_open?: boolean; output_style?: string }
  subagent_activity?: Array<{ role_id: string; title: string; status: string; summary: string }>
  developer_explanation?: string
  user_explanation?: string
  route_summary?: string
  intent_label?: string
  needs_clarification?: boolean
  clarification_question?: string
  missing_slots?: string[]
}

export type DeveloperDoneEvent = {
  lane: string
  workflow_id: string
  target_module: string
  status: string
  result: string
  iterations?: number
  profile?: ExecutionProfileSummary
  handoff?: Record<string, unknown>
  [key: string]: unknown
}

export type DevConsoleSnapshot = ConsoleSnapshot & {
  surface: "developer"
  profiles: ExecutionProfileSummary[]
  lane_status: {
    lanes: Array<{ id: string; queued: number }>
    total_queued: number
    active_tasks: number
  }
  subagent_roles: SubagentRoleSummary[]
  developer_actions: DeveloperActionSummary[]
  recent_trace_summary: RunTraceSummary
  mcp_servers?: Array<{ server_id: string; label: string; availability: string; workflows: string[]; workflow_families?: string[]; tool_names?: string[]; health_status?: string }>
}

export type WorkspaceCase = {
  id: string
  title: string
  workflow_title?: string
  risk_tier?: RiskTier
  risk_label?: string
  owner?: string
  queue?: string
  due_at?: string
  patient_label?: string
  service_line?: string
  focus?: string
  status_label?: string
  status_tone?: string
}

export type SummaryCard = {
  label: string
  value: string
}

export type EvidenceItem = {
  label: string
  value: string
}

export type WorkflowWorkspace = {
  id: string
  title: string
  status?: string
  owner?: string
  queue?: string
  due_at?: string
  patient_label?: string
  service_line?: string
  risk_tier?: RiskTier
  risk_label?: string
  risk_reason?: string
  rationale?: string[]
  summary_cards?: SummaryCard[]
  evidence_grid?: EvidenceItem[]
  recommended_actions?: string[]
  review?: {
    status?: string
    comment?: string
  }
  [key: string]: unknown
}

export type WorkflowSnapshot = {
  cases: WorkspaceCase[]
  queue_summary?: Record<string, number>
  default_case_id: string
  workspace: WorkflowWorkspace
}

export type ChatOptionModel = {
  id: string
  label: string
  supports_reasoning_effort: boolean
}

export type ChatOptionsSnapshot = {
  default_model: string
  default_reasoning_effort: "low" | "medium" | "high"
  models: ChatOptionModel[]
  reasoning_efforts: Array<"low" | "medium" | "high">
}

export type HealthSnapshot = {
  status: string
  provider: string
  model: string
  model_capabilities?: Record<string, unknown>
  neuro_report_provider?: string
  neuro_report_model?: string
  neuro_report_model_capabilities?: Record<string, unknown>
  dicomweb_base_url?: string
  ohif_base_url?: string
  workflow_families?: FamilyRegistryEntry[]
  workflow_registry?: WorkflowRegistryEntry[]
  mcp_servers?: Array<{ server_id: string; label: string; availability: string; workflows: string[]; workflow_families?: string[]; tool_names?: string[]; health_status?: string }>
  clinagent: {
    scenario_count: number
  }
}

export type NeuroKnowledgeHealth = {
  ok: boolean
  root?: string
  counts?: {
    cases?: number
    studies?: number
    series?: number
    assets?: number
  }
}

export type NeuroKnowledgeCohortEntry = {
  patient_uid: string
  study_count: number
  report_count: number
  has_mri_zip: number | boolean
  has_vista_seg: number | boolean
  has_nvseg: number | boolean
  case_label?: string
  cohort_shape?: string
  richness_score?: number
  study_uids?: string[]
  summary_text?: string
  cohort_tag?: string
  cohort_rank?: number
  selection_status?: string
  selection_reason?: string
}

export type NeuroKnowledgeCohortResponse = {
  ok: boolean
  cohort: NeuroKnowledgeCohortEntry[]
}

export type NeuroKnowledgeCaseRecord = {
  patient_uid: string
  study_count: number
  report_count: number
  has_mri_zip: number | boolean
  has_vista_seg: number | boolean
  has_nvseg: number | boolean
  cohort_tag?: string
  summary_path?: string
}

export type NeuroKnowledgeCaseSummary = {
  patient_uid: string
  study_count: number
  report_count: number
  case_label?: string
  study_dates?: string[]
  summary_text?: string
}

export type NeuroKnowledgeCaseStudy = {
  study_uid: string
  patient_uid: string
  anon_study_date?: string
  patient_age?: number
  patient_sex?: string
  report_available: number | boolean
  report_summary_path?: string
}

export type NeuroKnowledgeCase = {
  ok: boolean
  case: NeuroKnowledgeCaseRecord
  summary?: NeuroKnowledgeCaseSummary
  studies: NeuroKnowledgeCaseStudy[]
}

export type NeuroKnowledgeSegmentationMember = {
  member_path: string
  sequence_token?: string
  segmentation_family?: string
}

export type NeuroKnowledgeAsset = {
  asset_id: number
  patient_uid: string
  study_uid?: string | null
  asset_kind: string
  source_path: string
  batch_id?: string
  member_count: number
  available: number | boolean
  segmentation_family?: string | null
  segmentation_members?: NeuroKnowledgeSegmentationMember[]
}

export type NeuroKnowledgeAssetsResponse = {
  ok: boolean
  patient_uid: string
  assets: NeuroKnowledgeAsset[]
}

export type NeuroKnowledgeReport = {
  study_uid: string
  clinical_information?: string
  technique?: string
  findings?: string
  impression?: string
  report_text?: string
}

export type NeuroKnowledgeStudySummary = {
  study_uid: string
  patient_uid: string
  anon_study_date?: string
  summary_text?: string
}

export type NeuroKnowledgeStudy = {
  ok: boolean
  study: NeuroKnowledgeCaseStudy
  report?: NeuroKnowledgeReport | null
  summary?: NeuroKnowledgeStudySummary | null
  series?: Array<Record<string, unknown>>
}

export type NeuroKnowledgeLaunchLocalBundle = {
  image_path: string
  seg_path?: string | null
  supported_modes: string[]
}

export type NeuroKnowledgeLaunchResponse = {
  ok: boolean
  patient_uid: string
  study_uid: string
  local_status: "ready_local" | "downloaded" | "missing" | "failed"
  local_bundle?: NeuroKnowledgeLaunchLocalBundle | null
  knowledge_context?: {
    case?: NeuroKnowledgeCaseRecord
    study?: NeuroKnowledgeCaseStudy
    case_summary?: NeuroKnowledgeCaseSummary | null
    study_summary?: NeuroKnowledgeStudySummary | null
    report?: NeuroKnowledgeReport | null
  } | null
  download_summary?: {
    cache_hit?: boolean
    downloaded?: boolean
    local_dir?: string
  } | null
}

export type NeuroKnowledgeSearchResult = {
  patient_uid: string
  study_uid?: string
  anon_study_date?: string
  match_type?: string
  snippet?: string
  summary_text?: string
  case_label?: string
  findings?: string
  impression?: string
}

export type NeuroKnowledgeSearchResponse = {
  ok: boolean
  query: string
  results: NeuroKnowledgeSearchResult[]
}

export type NeuroWorkspaceTab = "overview" | "segmentation" | "alignment" | "trend" | "report"

export type NeuroAlignmentWorkflow = "longitudinal_coregistration" | "sequence_coregistration"

export type NeuroAlignmentJobRequest = {
  workflow: NeuroAlignmentWorkflow
  patient_id?: string | null
  fixed_study_id?: string | null
  moving_study_id?: string | null
  apply_to_segmentation?: boolean
  mode?: "demo" | "remote"
}

export type NeuroAlignmentJobResponse = {
  job_id: string
  status: "completed" | "failed" | "running" | "queued" | string
  mode: "demo" | "remote" | string
  workflow: NeuroAlignmentWorkflow | string
  patient_id?: string | null
  fixed_study_id?: string | null
  moving_study_id?: string | null
  apply_to_segmentation?: boolean
  clinical_summary?: string
  error?: string
  stages?: Array<{ stage: string; label: string; status: string }>
  qc?: {
    translation_mm?: number[]
    translation_norm_mm?: number
    ncc_before?: number
    ncc_after?: number
    ncc_delta?: number
    resampled_to_reference_grid?: boolean
    nonlinear_deformation_allowed?: boolean
    warnings?: string[]
    clinical_warnings?: string[]
  }
  outputs?: Record<string, string | null | undefined>
}
