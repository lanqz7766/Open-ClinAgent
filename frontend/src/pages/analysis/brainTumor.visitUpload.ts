import type { ModalityKey, UploadedCase, UploadSegmentJob, LongitudinalPoint } from "./brainTumor.types"

export type UploadVisitDraft = { id: string; date: string; folder: string; files: Partial<Record<ModalityKey, File>>; unassigned: File[] }
const keys: ModalityKey[] = ["t1n", "t1c", "t2w", "t2f"]

export const emptyVisitDraft = (): UploadVisitDraft => ({ id: crypto.randomUUID(), date: "", folder: "", files: {}, unassigned: [] })

export function groupVisitFiles(files: File[], infer: (name: string) => { modality: ModalityKey } | null): UploadVisitDraft[] {
  const groups = new Map<string, File[]>()
  for (const file of files) {
    if (!/\.nii(\.gz)?$/i.test(file.name)) continue
    const path = (file.webkitRelativePath || file.name).replaceAll("\\", "/")
    const folder = path.split("/").slice(0, -1).join("/")
    groups.set(folder, [...(groups.get(folder) || []), file])
  }
  if (!groups.size) throw new Error("No NIfTI files found. Choose a NIfTI ZIP, folder or four files.")
  if (groups.size > 6) throw new Error("A case can contain up to six visits.")
  return [...groups].sort(([a], [b]) => a.localeCompare(b, undefined, { numeric: true })).map(([folder, selected]) => {
    if (selected.length > 4 || (groups.size > 1 && selected.length !== 4)) {
      throw new Error("Keep each visit's four NIfTI files together in its own folder. Do not mix multiple visits in one folder.")
    }
    const draft = { ...emptyVisitDraft(), folder: folder.split("/").at(-1) || "Selected files" }
    for (const file of selected) {
      const key = infer(file.name)?.modality
      if (key && !draft.files[key]) draft.files[key] = file
      else draft.unassigned.push(file)
    }
    return draft
  })
}

export function validateVisitDrafts(visits: UploadVisitDraft[], existingDates: Array<string | null | undefined> = []): string | null {
  if (!visits.length || visits.length + existingDates.length > 6) return "A case can contain up to six visits."
  const files = visits.flatMap((visit) => keys.map((key) => visit.files[key]))
  if (visits.some((visit) => visit.unassigned.length) || files.some((file) => !file)) return "Assign all four modalities for every visit."
  if (new Set(files).size !== files.length) return "The same file is assigned more than once. Check each visit's mapping."
  if (files.some((file) => !/\.nii(\.gz)?$/i.test(file!.name) || !file!.size)) return "Each modality must be a non-empty NIfTI file."
  if (files.some((file) => file!.size > 350 * 1024 * 1024)) return "Each NIfTI file must be 350 MB or smaller."
  if (files.reduce((sum, file) => sum + file!.size, 0) > 1024 * 1024 * 1024) return "The uploaded files must be 1 GB or smaller in total."
  const dates = [...existingDates, ...visits.map((visit) => visit.date)].filter((value): value is string => Boolean(value))
  for (let index = 0; index < dates.length; index++) {
    const value = dates[index]
    const parsed = new Date(`${value}T00:00:00Z`)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) return "Enter a valid date, or leave it blank."
    if (index && value < dates[index - 1]) return "Dates conflict with the visit order. Check the dates or reorder the new visits."
  }
  return null
}

export function uploadCasePoints(uploaded: UploadedCase, job?: UploadSegmentJob | null): LongitudinalPoint[] {
  const visits = uploaded.visits?.length ? uploaded.visits : [{ id: "visit_01", date: null, status: "queued", modality_volume_urls: uploaded.modality_volume_urls }]
  return visits.map((visit, index) => {
    const update = job?.visits?.find((item) => item.id === visit.id)
    const session = update?.session || visit.session || (visits.length === 1 ? job?.session : null)
    return {
      id: `${uploaded.id}:${visit.id}`, timepointId: visit.id, sessionId: session?.session_id || "",
      label: `${uploaded.label} · Visit ${index + 1}`, dateLabel: visit.date || `Visit ${index + 1}`,
      scanDate: visit.date || null,
      relativeDay: visit.relative_day ?? null,
      relativeDayOrigin: visit.relative_day_origin ?? null,
      role: index === 0 ? "pre_treatment_baseline" : "follow_up", reviewState: "pending",
      volumes: session?.volumes || [], modalityVolumeUrls: session?.viewer_assets?.modality_volume_urls || visit.modality_volume_urls,
      segmentationUrl: session?.viewer_assets?.segmentation_url, overlayUrl: session?.viewer_assets?.overlay_preview_url,
      reportSlices: session?.viewer_assets?.report_slices, viewerType: "nifti_volume",
      previewProvenance: visit.date ? "Uploaded MRI · Date entered by uploader" : "Uploaded MRI · Date not provided",
    }
  })
}
