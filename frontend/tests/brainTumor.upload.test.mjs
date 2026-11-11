import assert from "node:assert/strict"
import { test } from "node:test"
import { readUploadJob, sendUpload, validateUploadFiles } from "../src/pages/analysis/brainTumor.upload.ts"

const files = () => ["T1", "T1c", "T2", "FLAIR"].map((name) => ({ name: `${name}.nii.gz`, size: 100 }))

test("single examination validation rejects mixed visits and invalid uploads", () => {
  assert.equal(validateUploadFiles(files()), null)
  assert.match(validateUploadFiles([...files(), ...files()]), /one examination/)
  const invalid = files(); invalid[0].name = "archive.zip"
  assert.match(validateUploadFiles(invalid), /extracting/)
  const empty = files(); empty[0].size = 0
  assert.match(validateUploadFiles(empty), /empty/)
  const large = files(); large[0].size = 351 * 1024 * 1024
  assert.match(validateUploadFiles(large), /350 MB/)
  assert.match(validateUploadFiles(files().map((file) => ({ ...file, size: 300 * 1024 * 1024 }))), /1 GB/)
  const duplicate = files(); duplicate[1] = duplicate[0]
  assert.match(validateUploadFiles(duplicate), /same file/)
})

test("upload uses one credentialed POST and reports bytes actually transferred", async (t) => {
  const original = globalThis.XMLHttpRequest
  let xhr
  globalThis.XMLHttpRequest = class {
    upload = {}
    constructor() { xhr = this }
    open(method, url) { this.method = method; this.url = url }
    send(body) { this.body = body }
  }
  t.after(() => { globalThis.XMLHttpRequest = original })
  const progress = []
  const body = new FormData()
  const pending = sendUpload(body, (value) => progress.push(value))
  assert.equal(xhr.method, "POST")
  assert.equal(xhr.withCredentials, true)
  assert.equal(xhr.body, body)
  xhr.upload.onprogress({ lengthComputable: true, loaded: 25, total: 100 })
  xhr.upload.onload()
  assert.deepEqual(progress, [25, 100])
  xhr.status = 200; xhr.responseText = JSON.stringify({ ok: true, job: { status: "queued" } }); xhr.onload()
  assert.equal((await pending).job.status, "queued")
})

test("uncertain upload response does not silently resubmit", async (t) => {
  const original = globalThis.XMLHttpRequest
  let count = 0
  globalThis.XMLHttpRequest = class {
    upload = {}
    open() {}
    send() { count += 1; this.onerror() }
  }
  t.after(() => { globalThis.XMLHttpRequest = original })
  await assert.rejects(sendUpload(new FormData(), () => {}), /Check My uploads/)
  assert.equal(count, 1)
})

test("job polling recovers from network and gateway failure without creating a new job", async (t) => {
  let calls = 0
  const states = []
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(options.credentials, "include")
    assert.equal(url, "/jobs/one")
    calls += 1
    if (calls === 1) throw new TypeError("offline")
    if (calls === 2) return new Response("Bad gateway", { status: 502 })
    return Response.json({ status: "completed" })
  })
  const job = await readUploadJob("/jobs/one", (state) => states.push(state), new AbortController().signal, async () => {})
  assert.equal(job.status, "completed")
  assert.deepEqual(states, [true, true, false])
  assert.equal(calls, 3)
})

test("expired sessions and deleted jobs are not endlessly retried", async (t) => {
  for (const status of [401, 404]) {
    let count = 0
    t.mock.method(globalThis, "fetch", async () => { count += 1; return new Response("", { status }) })
    await assert.rejects(readUploadJob("/jobs/one", () => {}, new AbortController().signal, async () => {}), status === 401 ? /Sign in/ : /no longer available/)
    assert.equal(count, 1)
  }
})

test("unmount cancellation prevents any further job request", async (t) => {
  let calls = 0
  t.mock.method(globalThis, "fetch", async () => { calls += 1; return Response.json({}) })
  const controller = new AbortController(); controller.abort()
  await assert.rejects(readUploadJob("/jobs/one", () => {}, controller.signal), /abort/i)
  assert.equal(calls, 0)
})

test("persistent status failure stops with a recovery action", async (t) => {
  let calls = 0
  t.mock.method(globalThis, "fetch", async () => { calls += 1; return new Response("", { status: 503 }) })
  await assert.rejects(readUploadJob("/jobs/one", () => {}, new AbortController().signal, async () => {}), /Reopen the case/)
  assert.equal(calls, 6)
})
