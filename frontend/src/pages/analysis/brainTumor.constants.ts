import type { ModalityKey, QcReasonKey } from "./brainTumor.types"

export const modalityMeta: Record<ModalityKey, { label: string; required: boolean; hint: string }> = {
  t1c: { label: "T1c", required: true, hint: "post-contrast T1" },
  t2f: { label: "FLAIR", required: true, hint: "T2-FLAIR" },
  t2w: { label: "T2", required: true, hint: "T2 weighted" },
  t1n: { label: "T1", required: true, hint: "pre-contrast T1" },
}

export const modalityOrder: ModalityKey[] = ["t2f", "t2w", "t1n", "t1c"]
export const requiredModalities: ModalityKey[] = ["t2f", "t2w", "t1n", "t1c"]
export const regionLabels: Record<string, string> = {
  whole_tumor: "Whole abnormality",
  flair_abnormality: "T2/FLAIR",
  enhancing_tumor: "CE tumor",
  cavity_or_post_surgical_change: "Cavity",
  tumor_core: "TC",
  non_enhancing_core_candidate: "NET candidate",
}
export const defaultTumorLabelIds = [1, 2, 3, 4]
export const tumorPalette = {
  et: "#d65f73",
  tc: "#7560ad",
  wt: "#3489bd",
  edema: "#4e9a92",
  net: "#7c6fbb",
  rc: "#9a7a43",
} as const

export const qcReasonOptions: Array<{ key: QcReasonKey; label: string }> = [
  { key: "modality_mapping", label: "Modality mapping wrong" },
  { key: "registration", label: "Registration failed" },
  { key: "overlay_accuracy", label: "Tumor overlay inaccurate" },
  { key: "wrong_timepoint", label: "Wrong patient / timepoint" },
  { key: "image_quality", label: "Image quality issue" },
]
