import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import vm from "node:vm"
import ts from "typescript"
import { groupVisitFiles, validateVisitDrafts, uploadCasePoints } from "../src/pages/analysis/brainTumor.visitUpload.ts"

const timing = {}
vm.createContext(timing)
vm.runInContext(ts.transpile(readFileSync(new URL("../src/pages/analysis/brainTumor.timing.ts", import.meta.url), "utf8").replaceAll("export ", ""), { target: ts.ScriptTarget.ES2022 }), timing)

const keys = ["t1n", "t1c", "t2w", "t2f"]
const infer = (name) => keys.includes(name.split(".")[0]) ? { modality: name.split(".")[0] } : null
function files(visit) {
  return keys.map((key) => {
    const file = new File([new Uint8Array([visit])], `${key}.nii.gz`)
    Object.defineProperty(file, "webkitRelativePath", { value: `case/visit_${visit}/${file.name}` })
    return file
  })
}
test("groups folders in natural order without inferring dates", () => {
  const groups = groupVisitFiles([...files(3), ...files(1), ...files(2)], infer)
  assert.deepEqual(groups.map((visit) => visit.folder), ["visit_1", "visit_2", "visit_3"])
  assert.ok(groups.every((visit) => visit.date === ""))
  assert.equal(validateVisitDrafts(groups), null)
  assert.throws(() => groupVisitFiles([...files(1), files(2)[0]], infer), /each visit/)
})
test("manual dates validate against order and existing visits, without filling unknown dates", () => {
  const groups = groupVisitFiles([...files(1), ...files(2)], infer)
  groups[0].date = "2026-01-10"
  groups[1].date = "2026-02-30"
  assert.match(validateVisitDrafts(groups), /valid date/)
  groups[1].date = "2025-01-01"
  assert.match(validateVisitDrafts(groups), /order/)
  groups[1].date = ""
  assert.equal(validateVisitDrafts(groups), null)
  assert.match(validateVisitDrafts(groups, ["2026-03-01"]), /order/)
  groups[0].date = ""
  groups[1].files.t1n = groups[0].files.t1n
  assert.match(validateVisitDrafts(groups), /more than once/)
})
test("unknown or duplicate modality names remain unassigned, never silently discarded", () => {
  const input = files(1)
  input[0] = new File(["x"], "unknown.nii.gz")
  // Flat selections are one visit; directory grouping is not inferred from anatomy.
  const flat = input.map((file) => new File([file], file.name))
  const groups = groupVisitFiles(flat, infer)
  assert.equal(groups[0].unassigned.length, 1)
  assert.match(validateVisitDrafts(groups), /Assign all four/)
})
test("partial jobs and restored cases retain all visits with stable IDs and raw images", () => {
  const uploaded = { id: "upload_test", label: "Case A", visits: [1, 2, 3].map((i) => ({ id: `visit_0${i}`, date: i === 2 ? "2026-02-01" : null, modality_volume_urls: { t1c: `raw-${i}` } })) }
  const job = { visits: [{ id: "visit_01", status: "complete", session: { session_id: "seg-1", volumes: [{ region: "enhancing_tumor", volume_ml: 3 }], viewer_assets: { segmentation_url: "mask-1" } } }] }
  const points = uploadCasePoints(uploaded, job)
  assert.equal(points.length, 3)
  assert.equal(points[0].id, "upload_test:visit_01")
  assert.equal(points[0].sessionId, "seg-1")
  assert.equal(points[1].modalityVolumeUrls.t1c, "raw-2")
  assert.equal(points[1].dateLabel, "2026-02-01")
  assert.equal(points[2].dateLabel, "Visit 3")
  assert.deepEqual(points[2].volumes, [])
})

test("unfinished visits never become measured decreases or change the measured nadir", () => {
  const file = ts.createSourceFile("logic.ts", readFileSync(new URL("../src/pages/analysis/brainTumor.logic.ts", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true)
  const body = file.statements.filter((node) => !ts.isImportDeclaration(node)).map((node) => node.getText(file)).join("\n")
  const context = { exports: {}, annotateVisitTiming: timing.annotateVisitTiming }
  vm.createContext(context)
  vm.runInContext(ts.transpile(body, { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), context)
  const points = [{ id: "a", volumes: [{ region: "enhancing_tumor", volume_ml: 10 }] }, { id: "b", volumes: [] }, { id: "c", volumes: [{ region: "enhancing_tumor", volume_ml: 12 }] }]
  const rows = context.exports.buildLongitudinalRows(points, "a")
  assert.equal(rows[1].etChangePct, null)
  assert.equal(rows[1].etNadirChangePct, null)
  assert.equal(rows[2].etChangePct, 20)
  assert.equal(rows[2].etNadirChangePct, 20)
  assert.equal(context.exports.buildLongitudinalRows(points, "b")[2].etChangePct, null)
})
