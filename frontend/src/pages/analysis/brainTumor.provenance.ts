import type { LongitudinalPoint, RegistrationQc } from "./brainTumor.types"

export function isRegistered(registration?: RegistrationQc): boolean {
  return Boolean(
    registration?.backend
    && registration.backend !== "affine_header_qc"
    && ["ok", "complete", "completed", "success"].includes(registration.status ?? ""),
  )
}

export function registrationLabel(registration?: RegistrationQc): string {
  if (!registration) return "Not aligned"
  if (registration.backend === "affine_header_qc") return "Geometry checked"
  if (!isRegistered(registration)) return "Alignment unverified"
  const delta = registration.ncc_delta
  return typeof delta === "number" && Number.isFinite(delta)
    ? `Aligned · NCC Δ ${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`
    : "Aligned · NCC unavailable"
}

export function beginCaseReview(points: LongitudinalPoint[]): LongitudinalPoint[] {
  return points.map((point) => ({
    ...point,
    curationReviewState: point.curationReviewState ?? point.reviewState,
    reviewState: "pending",
  }))
}
