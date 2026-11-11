export type InputMode = "dicomweb" | "mount" | "upload"
export type ModalityKey = "t1n" | "t1c" | "t2w" | "t2f"
export type ReviewState = "pending" | "accepted" | "needs_revision" | "excluded"
export type WorkflowStatus = "complete" | "active" | "pending" | "blocked"
export type TimepointRole = "pre_treatment_baseline" | "post_rt_baseline" | "follow_up" | "screening_baseline" | "nadir"
export type QcReasonKey = "modality_mapping" | "registration" | "overlay_accuracy" | "wrong_timepoint" | "image_quality"
export type ReportSlicePlane = "axial" | "coronal" | "sagittal"

export type ReportSliceAsset = {
  url?: string
  slice_index?: number | null
  modality?: string
}

export type ReportSlices = {
  modality?: string
} & Partial<Record<ReportSlicePlane, ReportSliceAsset>>

export type ServiceStatus = {
  ok: boolean
  ready: boolean
  service_url_configured: boolean
  model_id?: string
  error?: string
  physician_curated_only?: boolean
  model_info?: {
    model_id?: string
    input_modalities?: string[]
  }
}

export type DicomStudy = {
  study_instance_uid: string
  patient_id: string
  modality: string
  description: string
  study_date: string
  series_count: number
}

export type MountedDicomStatus = {
  ok: boolean
  configured: boolean
  root_count: number
  remote: boolean
  scan_limit: number
}

export type DicomSeries = {
  series_instance_uid: string
  description: string
  modality: string
  instance_count: number
  candidate_modality?: ModalityKey | null
  candidate_score?: number
  candidate_reason?: string
}

export type TumorSession = {
  ok: boolean
  session_id: string
  status?: string
  patient_label?: string
  modality_status: Record<ModalityKey, { present: boolean; required: boolean; path_name: string }>
  volumes: Array<{ region: string; volume_ml: number; voxel_count?: number }>
  qc: { warnings?: string[]; intended_use?: string }
  report_snippet: { findings: string; impression: string; copy_text: string }
  service: { model_id?: string; mode?: string; remote_staging?: { enabled?: boolean } }
  viewer_assets?: {
    overlay_preview_url?: string
    segmentation_url?: string
    modality_volume_urls?: Partial<Record<ModalityKey, string>>
    report_slices?: ReportSlices | null
  }
  artifact_urls?: Record<string, string>
}

export type RegistrationQc = {
  status?: string
  backend?: string
  deformation_model?: string
  nonlinear_deformation_allowed?: boolean
  translation_norm_mm?: number
  ncc_before?: number | null
  ncc_after?: number | null
  ncc_delta?: number | null
  warnings?: string[]
  baseline_session_id?: string
  rotation_angle_deg?: number
  registration_runtime_sec?: number
  similarity_metric?: string
  bias_correction?: boolean
  steps?: AlignmentStep[]
  modality_volume_urls?: Partial<Record<ModalityKey, string>>
  segmentation_url?: string
  ground_truth_segmentation_url?: string
}

export type AlignmentStep = {
  id: string
  label: string
  tool: string
  status: "pending" | "running" | "complete" | "skipped" | "failed"
  detail?: string
  duration_sec?: number
}

export type LongitudinalPoint = {
  id: string
  sessionId: string
  timepointId?: string
  label: string
  role: TimepointRole
  dateLabel: string
  scanDate?: string | null
  relativeDay?: number | null
  relativeDayOrigin?: string | null
  reviewState: ReviewState
  curationReviewState?: ReviewState
  volumes: Array<{ region: string; volume_ml: number; voxel_count?: number }>
  overlayUrl?: string
  groundTruthOverlayUrl?: string
  modalityPreviewUrls?: Partial<Record<ModalityKey, string>>
  modalityVolumeUrls?: Partial<Record<ModalityKey, string>>
  segmentationUrl?: string
  reportSlices?: ReportSlices | null
  groundTruthSegmentationUrl?: string
  viewerType?: "nifti_volume" | "static_preview"
  previewProvenance?: string
  registration?: RegistrationQc
  stageLabel?: string
}

export type PreloadExample = {
  id: string
  title: string
  description?: string
  source_note?: string
  display_mode?: "stage_comparison" | "response_trend" | "cohort"
  same_patient_longitudinal?: boolean
  points: LongitudinalPoint[]
}

export type PreloadExampleMeta = {
  title: string
  description: string
  sourceNote: string
  displayMode?: "stage_comparison" | "response_trend" | "cohort"
  samePatientLongitudinal: boolean
}

export type UploadInferenceRow = {
  fileName: string
  modality: ModalityKey | null
  reason: string
}

export type UploadedCase = {
  id: string
  label: string
  created_at?: string
  expires_at?: string
  retention_days?: number
  modalities: Partial<Record<ModalityKey, { shape?: number[]; spacing_mm?: number[] }>>
  modality_volume_urls: Partial<Record<ModalityKey, string>>
  resample_to_t1c?: ModalityKey[]
  visit_count?: number
  visits?: UploadedVisit[]
  job?: UploadSegmentJob | null
}

export type UploadedVisit = {
  id: string
  date?: string | null
  relative_day?: number | null
  relative_day_origin?: string | null
  status?: string
  session_id?: string | null
  session?: TumorSession | null
  modality_volume_urls?: Partial<Record<ModalityKey, string>>
}

export type UploadSegmentJob = {
  ok: boolean
  job_id: string
  case_id: string
  status: "queued" | "running" | "completed" | "failed"
  stage?: "queued" | "starting" | "preparing" | "segmenting" | "complete" | "failed"
  total_count: number
  completed_count: number
  failed_count?: number
  session_id?: string
  session?: TumorSession | null
  visits?: UploadedVisit[]
  active_visit_index?: number
  error?: string
}

export type BrainTumorReportDraftResponse = {
  ok: boolean
  generated: boolean
  report_text: string
  model?: string
  warning?: string
  error?: string
}

export type RegistryTimepoint = {
  id: string
  label: string
  dateLabel: string
  role: TimepointRole
  modalities: string[]
  gt_available?: boolean
}

export type RegistryCase = {
  id: string
  title: string
  dataset?: string
  patient_id?: string
  description?: string
  timepoint_count: number
  gt_available?: boolean
  demo_quality?: {
    cache_count?: number
    recommended?: boolean
    note?: string
    max_enhancing_ml?: number
    max_flair_ml?: number
    max_cavity_ml?: number
    max_cavity_to_wt?: number
  }
  timepoints: RegistryTimepoint[]
}

export type RegistrySegmentJobVisit = {
  timepoint_id: string
  label: string
  dateLabel: string
  role: TimepointRole
  status: "queued" | "running" | "complete" | "failed"
  point?: LongitudinalPoint | null
  session?: TumorSession | null
  error?: string | null
}

export type RegistrySegmentJob = {
  ok: boolean
  job_id: string
  case_id: string
  status: "queued" | "running" | "completed" | "completed_with_errors" | "failed"
  stage?: "queued" | "starting" | "preparing" | "segmenting" | "materializing" | "finalizing" | "complete" | "completed_with_errors" | "failed"
  total_count: number
  completed_count: number
  failed_count?: number
  same_patient_longitudinal?: boolean
  visits: RegistrySegmentJobVisit[]
  force_rerun?: boolean
  error?: string
}

export type LongitudinalAlignJobVisit = {
  session_id: string
  baseline_session_id?: string | null
  followup_session_id?: string | null
  label?: string
  dateLabel?: string
  status: "reference" | "queued" | "running" | "complete" | "failed"
  registration?: RegistrationQc | null
  error?: string | null
  steps?: AlignmentStep[]
}

export type LongitudinalAlignJob = {
  ok: boolean
  job_id: string
  status: "running" | "completed" | "completed_with_errors" | "failed"
  baseline_session_id: string
  total_count: number
  completed_count: number
  failed_count?: number
  visits: LongitudinalAlignJobVisit[]
  error?: string
  bias_correction?: boolean
}
export type LongitudinalRow = LongitudinalPoint & {
  timingSamePatient: boolean
  firstVisit: boolean
  intervalDays: number | null
  daysFromReference: number | null
  isReference: boolean
  etMl: number
  wtMl: number
  tcMl: number
  netMl: number
  flairMl: number
  rcMl: number
  etChangePct: number | null
  flairChangePct: number | null
  wtChangePct: number | null
  etNadirChangePct: number | null
}
