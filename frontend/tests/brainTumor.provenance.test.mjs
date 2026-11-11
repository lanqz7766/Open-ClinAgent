import assert from "node:assert/strict"
import test from "node:test"
import { beginCaseReview, isRegistered, registrationLabel } from "../src/pages/analysis/brainTumor.provenance.ts"

test("header QC is not a completed registration", () => {
  const qc = { backend: "affine_header_qc", status: "ok", ncc_delta: 0 }
  assert.equal(isRegistered(qc), false)
  assert.equal(registrationLabel(qc), "Geometry checked")
  assert.equal(isRegistered({ status: "complete" }), false)
  assert.equal(isRegistered({ backend: "simpleitk_rigid", status: "failed" }), false)
})

test("actual alignment displays zero and missing NCC honestly", () => {
  const qc = { backend: "simpleitk_rigid", status: "ok", ncc_delta: 0 }
  assert.equal(isRegistered(qc), true)
  assert.equal(registrationLabel(qc), "Aligned · NCC Δ +0.00")
  assert.equal(registrationLabel({ ...qc, ncc_delta: null }), "Aligned · NCC unavailable")
  assert.equal(registrationLabel(undefined), "Not aligned")
})

test("curation acceptance never accepts the current user's review", () => {
  const original = [{ id: "scan-1", reviewState: "accepted", volumes: [] }]
  const reviewed = beginCaseReview(original)
  assert.equal(reviewed[0].reviewState, "pending")
  assert.equal(reviewed[0].curationReviewState, "accepted")
  assert.equal(original[0].reviewState, "accepted")
})
