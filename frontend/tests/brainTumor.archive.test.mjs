import assert from "node:assert/strict"
import { test } from "node:test"
import { BlobWriter, Uint8ArrayReader, ZipWriter } from "@zip.js/zip.js"
import { prepareNiftiSelection } from "../src/pages/analysis/brainTumor.archive.ts"

const names = ["T1.nii.gz", "T1c.nii.gz", "T2.nii.gz", "FLAIR.nii.gz"]
const bytes = new TextEncoder().encode("synthetic imaging bytes for archive tests")
const entries = () => names.map((name) => [`example_01/${name}`, bytes])
async function zip(rows = entries(), options = {}) {
  const writer = new ZipWriter(new BlobWriter(), { useWebWorkers: false, ...options })
  for (const [name, data] of rows) await writer.add(name, new Uint8ArrayReader(data))
  return new File([await writer.close()], "example.zip")
}
const extract = (file, onProgress = () => {}, signal = new AbortController().signal) => prepareNiftiSelection([file], onProgress, signal)

test("stored and compressed example ZIPs extract byte-identical files and ignore guide/metadata", async () => {
  for (const level of [0, 6]) {
    const progress = []
    const file = await zip([...entries(), ["example_01/README.txt", bytes], ["__MACOSX/example_01/._T1.nii.gz", bytes], ["example_01/.DS_Store", bytes]], { level })
    const result = await extract(file, (state) => progress.push(state))
    assert.deepEqual(result.map((item) => item.name), names)
    for (const item of result) assert.deepEqual(new Uint8Array(await item.arrayBuffer()), bytes)
    assert.equal(progress[0].phase, "reading")
    assert.equal(progress.at(-1).phase, "ready")
    assert.equal(progress.at(-1).percent, 100)
    assert.ok(progress.some((state) => state.phase === "extracting" && state.completed === 1))
    assert.ok(progress.every((state, i) => !i || state.percent >= progress[i - 1].percent))
  }
})

test("ordinary file selections pass through unchanged and never need decompression", async () => {
  const files = names.map((name) => new File([bytes], name))
  assert.equal(await prepareNiftiSelection(files, () => assert.fail("No ZIP progress"), new AbortController().signal), files)
})

test("reject mixed ZIP/files and multiple ZIPs instead of combining visits", async () => {
  const file = await zip()
  for (const extra of [file, new File([bytes], "T1.nii.gz")]) {
    await assert.rejects(prepareNiftiSelection([file, extra], () => {}, new AbortController().signal), /one ZIP/)
  }
})

test("reject incomplete archives without returning partial selections", async () => {
  await assert.rejects(extract(await zip(entries().slice(0, 3))), /Found 3/)
  await assert.rejects(extract(await zip([...entries(), ["followup/another_T1.nii.gz", bytes]])), /Found 5/)
  await assert.rejects(extract(await zip([["image.dcm", bytes]])), /DICOM ZIP is not supported/)
  await assert.rejects(extract(await zip([])), /Found 0/)
})

test("reject duplicate paths, invalid paths and empty imaging files", async () => {
  await assert.rejects(extract(await zip([...entries().slice(0, 3), ["example_01/t1.NII.GZ", bytes]])), /Duplicate/)
  await assert.rejects(extract(await zip([["../T1.nii.gz", bytes], ...entries().slice(1)])), /invalid file path|could not be read/)
  await assert.rejects(extract(await zip([["/T1.nii.gz", bytes], ...entries().slice(1)])), /invalid file path|could not be read/)
  await assert.rejects(extract(await zip([["T1.nii.gz", new Uint8Array()], ...entries().slice(1)])), /empty/)
})

test("three visits keep distinct relative paths and report all twelve extracted files", async () => {
  const progress = []
  const rows = [1, 2, 3].flatMap((visit) => names.map((name) => [`case/visit_0${visit}/${name}`, new Uint8Array([visit])]))
  const result = await extract(await zip(rows), (value) => progress.push(value))
  assert.equal(result.length, 12)
  assert.equal(result[4].webkitRelativePath, "case/visit_02/T1.nii.gz")
  assert.deepEqual(new Uint8Array(await result[4].arrayBuffer()), new Uint8Array([2]))
  assert.equal(progress.at(-1).completed, 12)
  assert.equal(progress.at(-1).total, 12)
})

test("reject encrypted, damaged and truncated ZIPs", async () => {
  await assert.rejects(extract(await zip(entries(), { password: "synthetic-test-password" })), /Password-protected/)
  await assert.rejects(extract(new File([bytes], "bad.zip")), /could not be read/)
  const file = await zip()
  await assert.rejects(extract(new File([file.slice(0, -30)], "truncated.zip")), /could not be read/)
  const raw = new Uint8Array(await (await zip(entries(), { level: 0 })).arrayBuffer())
  const payloadOffset = Buffer.from(raw).indexOf(Buffer.from(bytes))
  assert.ok(payloadOffset > 0)
  raw[payloadOffset] ^= 255
  await assert.rejects(extract(new File([raw], "corrupt.zip")), /could not be read/)
})

test("ZIP input size and declared extracted sizes are bounded before decompression", async () => {
  await assert.rejects(extract(new File([], "empty.zip")), /empty/)
  const oversized = new File([bytes], "big.zip")
  Object.defineProperty(oversized, "size", { value: 1024 ** 3 + 1 })
  await assert.rejects(extract(oversized), /1 GB/)
  const original = new Uint8Array(await (await zip()).arrayBuffer())
  const centralHeaders = []
  for (let offset = 0; offset < original.length - 4; offset++) {
    if (new DataView(original.buffer).getUint32(offset, true) === 0x02014b50) centralHeaders.push(offset)
  }
  assert.equal(centralHeaders.length, 4)
  const tooLarge = original.slice()
  new DataView(tooLarge.buffer).setUint32(centralHeaders[0] + 24, 351 * 1024 ** 2, true)
  await assert.rejects(extract(new File([tooLarge], "big-file.zip")), /350 MB/)
  const tooMuch = original.slice()
  for (const offset of centralHeaders) new DataView(tooMuch.buffer).setUint32(offset + 24, 300 * 1024 ** 2, true)
  await assert.rejects(extract(new File([tooMuch], "big-total.zip")), /1 GB/)
})

test("cancel before reading or during extraction never returns ready files", async () => {
  const file = await zip()
  const cancelled = new AbortController(); cancelled.abort()
  await assert.rejects(extract(file, () => {}, cancelled.signal), /abort/i)
  const controller = new AbortController()
  const phases = []
  await assert.rejects(extract(file, (state) => {
    phases.push(state.phase)
    if (state.phase === "extracting" && state.completed === 1) controller.abort()
  }, controller.signal), /abort/i)
  assert.ok(!phases.includes("ready"))
})
