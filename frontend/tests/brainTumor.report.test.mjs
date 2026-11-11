import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

function sourceFile(name) {
  return ts.createSourceFile(name, readFileSync(new URL(`../src/pages/analysis/${name}`, import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
}
const timingSource = sourceFile("brainTumor.timing.ts")
const timing = load(timingSource, timingSource.statements.filter(ts.isFunctionDeclaration).map(node => node.name.text))
const page = sourceFile("BrainTumorPage.tsx")
const logic = sourceFile("brainTumor.logic.ts")

function extract(source, names) {
  const found = []
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.includes(node.name?.text)) found.push(node.getText(source).replace(/^export /, ""))
    if (ts.isVariableStatement(node) && node.declarationList.declarations.some((item) => names.includes(item.name.getText(source)))) found.push(node.getText(source))
    ts.forEachChild(node, visit)
  }
  visit(source)
  return found.join("\n")
}
function load(source, names, values = {}) {
  const context = vm.createContext(values)
  vm.runInContext(ts.transpile(extract(source, names), { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React }), context)
  return context
}

const prose = load(page, ["parseReportSections", "reportHeadingLabels", "ReportText", "renderReportLine", "renderInlineMarkdown"], { React })

test("bold fields and volumes stay together instead of becoming separate headings", () => {
  const sections = prose.parseReportSections("**Case context:**\n**Case:** Example 01\n**Scan:** Visit 1\n**Key measurements:**\n- **CE tumor:** 1,234 mm³\n**Impression:**\nReference scan.")
  assert.deepEqual(Array.from(sections, (item) => item.heading), ["Case context", "Key measurements", "Impression"])
  assert.equal(sections[0].paragraphs[0], "**Case:** Example 01")
  assert.equal(sections[1].bullets[0], "**CE tumor:** 1,234 mm³")
})

test("plain, Markdown and inline section headings render with no empty sections", () => {
  const sections = prose.parseReportSections("## Basic information\nCase: Example\nFindings:\n**Impression:** Reference scan.\nQC / provenance:\nMask review: Pending")
  assert.deepEqual(Array.from(sections, (item) => item.heading), ["Basic information", "Impression", "QC / provenance"])
  assert.equal(sections[1].paragraphs[0], "Reference scan.")
})

test("draft text remains escaped and important labels render as strong text", () => {
  const html = renderToStaticMarkup(prose.ReportText({ text: "Findings:\n- **CE tumor:** 1,234 mm³\n<script>alert(1)</script>" }))
  assert.match(html, /<h3>Findings<\/h3>/)
  assert.match(html, /<strong[^>]*>CE tumor:<\/strong>/)
  assert.ok(!html.includes("<script>"))
  assert.ok(html.includes("&lt;script&gt;"))
})

const reportLogic = load(logic, ["htmlDeltaClass", "buildHtmlMeasurementRows", "buildMeasurementsCsv", "csvEscape", "escapeHtml", "buildVisitTimingText", "localVisitTimingDetail", "activePointReport", "activePointImpression", "buildReportExportText", "buildReportPayload", "measurementPayload", "buildReportFigureSvg", "buildSvgDonut", "svgLegend", "formatMm3", "formatMm3Number", "formatPct", "reviewStateLabel", "mm3Integer", "csvNumber", "roleLabel"], {
  visitTimingLabel: timing.visitTimingLabel,
  visitTimeLabel: timing.visitTimeLabel,
  normalizeRelativeDay: timing.normalizeRelativeDay,
  formatDay: timing.formatDay,
  timelineScale: timing.timelineScale,
  timelineTicks: timing.timelineTicks,
  tumorPalette: { et: "#a33b51", wt: "#2872a1", rc: "#9a8050" },
  isRegistered: (registration) => registration?.status === "aligned",
  registrationLabel: () => "Pending",
  qcReasonLabel: (reason) => reason,
})
const point = { id: "scan-1", sessionId: "session-1", label: "Example 01", dateLabel: "Visit 1", isReference: true, segmentationUrl: "/mask", etMl: 1.234, flairMl: 9, wtMl: 11, rcMl: 0, tcMl: 2, netMl: 0.766, etChangePct: 0 }

test("reference scan never claims that existing follow-up visits are unavailable", () => {
  const impression = reportLogic.activePointImpression(point)
  assert.match(impression, /selected reference/)
  assert.doesNotMatch(impression, /until|follow-up is available/)
})

test("exports use selected measurements and impression, not a stale session snippet", () => {
  const oldSession = { report_snippet: { findings: "STALE_FINDINGS", impression: "STALE_IMPRESSION" } }
  const text = reportLogic.buildReportExportText("Example 01", "Visit 1", "pending", [], point, oldSession)
  assert.match(text, /CE tumor: 1,234 mm³/)
  assert.match(text, /Basic information:/)
  assert.match(text, /QC \/ provenance:/)
  assert.doesNotMatch(text, /STALE/)
  const payload = reportLogic.buildReportPayload("Example 01", "Visit 1", "pending", [], point, [point, { ...point, id: "scan-2", isReference: false }], oldSession)
  assert.equal(payload.segmentation.completed_count, 2)
  assert.equal(payload.segmentation.total_count, 2)
  assert.equal(payload.alignment.completed_count, 1)
  assert.equal(payload.alignment.total_count, 2)
  assert.doesNotMatch(payload.impression, /STALE/)
})

function draftHarness() {
  const state = {}
  const pending = []
  const timers = new Map()
  let timerId = 0
  const context = load(page, ["generateReportDraft"], {
    AbortController, Error,
    window: { setTimeout: (callback) => { timers.set(++timerId, callback); return timerId }, clearTimeout: (id) => timers.delete(id) },
    reportRequestRef: { current: null },
    hasLoadedCase: true, activeSegmentationReady: true, activeLabel: "Example 01", activeDate: "Visit 1", activeReviewState: "pending", activeQcReasons: [], activePoint: point, longitudinalRows: [point], session: null, samePatientLongitudinal: true,
    buildReportPayload: (...args) => { state.payloadArgs = args; return {} },
    buildReportExportText: () => "Structured measurements for the selected scan",
    fetch: (_url, options) => new Promise((resolve, reject) => {
      pending.push({ resolve: (payload) => resolve({ ok: true, json: async () => payload }), options })
      options.signal.addEventListener("abort", () => reject(new Error("aborted")))
    }),
    setGeneratedReportText: (value) => { state.text = value },
    setReportDraftSource: (value) => { state.source = value },
    setReportError: (value) => { state.error = value },
    setDraftingReport: (value) => { state.busy = value },
  })
  return { context, state, pending, timers }
}

test("generation shows busy state, uses current counts, and identifies an AI draft truthfully", async () => {
  const { context, state, pending, timers } = draftHarness()
  const task = context.generateReportDraft()
  assert.equal(state.busy, true)
  assert.equal(state.payloadArgs[7], undefined, "never pass a previous job's counts")
  pending[0].resolve({ ok: true, generated: true, report_text: "Findings:\nMeasured volumes." })
  await task
  assert.equal(state.source, "ai")
  assert.equal(state.busy, false)
  assert.equal(timers.size, 0)
})

test("a request from the previous selection cannot replace a newer draft or clear its busy state", async () => {
  const { context, state, pending } = draftHarness()
  const previous = context.generateReportDraft()
  context.reportRequestRef.current.abort()
  context.reportRequestRef.current = null
  const current = context.generateReportDraft()
  await previous
  assert.equal(state.busy, true)
  assert.equal(state.text, undefined)
  pending[1].resolve({ ok: true, generated: true, report_text: "Current scan" })
  await current
  assert.equal(state.text, "Current scan")
})

test("timeouts, empty responses and provider fallback preserve a usable structured draft", async () => {
  for (const mode of ["timeout", "empty", "local"]) {
    const { context, state, pending, timers } = draftHarness()
    const task = context.generateReportDraft()
    if (mode === "timeout") timers.values().next().value()
    else pending[0].resolve({ ok: true, generated: mode === "empty", report_text: mode === "empty" ? " " : "Server fallback" })
    await task
    assert.equal(state.source, "local", mode)
    assert.equal(state.text, "Structured measurements for the selected scan", mode)
    assert.match(state.error, /AI drafting is unavailable/, mode)
    assert.equal(state.busy, false)
    assert.equal(timers.size, 0)
  }
})

test("no report request can run before measurements are ready", async () => {
  const { context, pending } = draftHarness()
  context.activeSegmentationReady = false
  await context.generateReportDraft()
  assert.equal(pending.length, 0)
})

test("local text and payload retain visit timing, including same-day zero", () => {
  const dated = { ...point, scanDate: "2024-02-29", firstVisit: false, intervalDays: 0, daysFromReference: 29 }
  const text = reportLogic.buildReportExportText("Synthetic", dated.scanDate, "pending", [], dated, null, [dated])
  assert.match(text, /Scan date: 2024-02-29; Since previous visit: 0 days/)
  assert.match(text, /Offset from selected reference: 29 days/)
  const payload = reportLogic.measurementPayload(dated)
  assert.equal(payload.scan_date, "2024-02-29")
  assert.equal(payload.interval_days, 0)
  assert.equal(payload.days_from_reference, 29)
  assert.match(reportLogic.buildVisitTimingText([dated], false), /different patients/)
})

test("HTML and CSV preserve unknown timing and same-day zero", () => {
  const rows = [{ ...point, scanDate: "2024-02-29", firstVisit: true, intervalDays: null, daysFromReference: 0 }, { ...point, id: "scan-2", scanDate: "2024-02-29", firstVisit: false, intervalDays: 0, daysFromReference: 0 }, { ...point, id: "scan-3", scanDate: null, firstVisit: false, intervalDays: null, daysFromReference: null }]
  const html = reportLogic.buildHtmlMeasurementRows(rows, "scan-2")
  assert.match(html, /Scan date: 2024-02-29/)
  assert.match(html, /Since previous visit: 0 days/)
  assert.match(html, /Scan date: Unknown/)
  const csv = reportLogic.buildMeasurementsCsv(rows).split("\n").map(line => line.split(","))
  const interval = csv[0].indexOf("interval_days_since_previous_visit")
  assert.equal(csv[1][interval], "")
  assert.equal(csv[2][interval], "0")
  assert.equal(csv[3][interval], "")
})

function syntheticVisits(times) {
  return times.map((time, index) => ({ ...point, id: `scan-${index + 1}`, dateLabel: `Visit ${index + 1}`, scanDate: null, timingSamePatient: true, firstVisit: index === 0, isReference: index === 0, etMl: index + 1, ...time }))
}

function trendCoordinates(svg) {
  const paths = Array.from(svg.matchAll(/<path fill="none" d="([^"]*)"/g), match => match[1])
  assert.equal(paths.length, 2)
  assert.ok(paths.every(path => !/[CQST]/.test(path)), "visit measurements must not use spline interpolation")
  return paths.map(path => Array.from(path.matchAll(/[ML] ([\d.eE+-]+) ([\d.eE+-]+)/g), match => ({ x: Number(match[1]), y: Number(match[2]) })))
}

function axisTicks(svg) {
  return Array.from(svg.matchAll(/<text x="([\d.eE+-]+)" y="([\d.eE+-]+)" data-visit-tick=""[^>]*>([^<]*)<\/text>/g), match => ({ x: Number(match[1]), y: Number(match[2]), label: match[3] }))
}

test("HTML trend labels every actual calendar visit without shifting visits", () => {
  const rows = syntheticVisits(["2024-01-01", "2024-01-02", "2024-01-11"].map(scanDate => ({ scanDate })))
  const svg = reportLogic.buildReportFigureSvg(rows, rows[1].id)
  for (const coordinates of trendCoordinates(svg)) assert.deepEqual(coordinates.map(point => point.x), [70, 120, 570])
  assert.match(svg, /X-axis basis: Scan date/)
  const ticks = axisTicks(svg)
  assert.deepEqual(ticks.map(tick => tick.label), ["2024-01-01", "2024-01-02", "2024-01-11"])
  assert.notEqual(ticks[0].y, ticks[1].y)
  assert.equal(Array.from(svg.matchAll(/<circle[^>]+r="4"/g)).length, 6)
})

test("fractional relative days retain precise spacing while display uses at most one decimal", () => {
  const days = [0, 56.40625, 56.46180555555475, 120]
  const rows = syntheticVisits(days.map(relativeDay => ({ relativeDay, relativeDayOrigin: "first scan" })))
  const svg = reportLogic.buildReportFigureSvg(rows, rows[1].id)
  for (const coordinates of trendCoordinates(svg)) {
    coordinates.forEach((point, index) => assert.ok(Math.abs(point.x - (70 + days[index] / 120 * 500)) < 1e-10))
    assert.ok(coordinates[2].x > coordinates[1].x, "nearby visits must not be rounded onto the same coordinate")
    assert.ok(coordinates[2].x - coordinates[1].x < 1, "nearby visits must not be spread artificially")
  }
  assert.match(svg, /X-axis basis: Days from first scan/)
  assert.match(svg, /Day 56\.4/)
  assert.match(svg, /Day 56\.5/)
  assert.doesNotMatch(svg, /56\.40625|56\.461805/)
  const ticks = axisTicks(svg)
  assert.equal(ticks.length, 4)
  assert.notEqual(ticks[1].y, ticks[2].y)
  for (let i = 0; i < ticks.length; i++) {
    for (let j = i + 1; j < ticks.length; j++) {
      if (ticks[i].y === ticks[j].y) assert.ok(ticks[j].x - ticks[i].x >= (ticks[i].label.length + ticks[j].label.length) * 11 * 0.32 + 12)
    }
  }
})

test("partial or incomparable timing uses an explicitly ordinal chart axis", () => {
  for (const times of [
    [{ scanDate: "2024-01-01" }, {}, { scanDate: "2024-01-11" }],
    [{ relativeDay: 0, relativeDayOrigin: "first scan" }, {}, { relativeDay: 120, relativeDayOrigin: "first scan" }],
    [{ relativeDay: 0, relativeDayOrigin: "first scan" }, { relativeDay: 10, relativeDayOrigin: "surgery" }, { relativeDay: 120, relativeDayOrigin: "first scan" }],
  ]) {
    const rows = syntheticVisits(times)
    const svg = reportLogic.buildReportFigureSvg(rows)
    for (const coordinates of trendCoordinates(svg)) assert.deepEqual(coordinates.map(point => point.x), [70, 320, 570])
    assert.match(svg, /X-axis basis: Visit order.*timing unavailable/)
    assert.deepEqual(axisTicks(svg).map(tick => tick.label), ["Visit 1", "Visit 2", "Visit 3"])
  }
})

test("calendar dates take axis precedence; day axes never mix calendar and relative-day tick labels", () => {
  const relative = [{ relativeDay: 0 }, { relativeDay: 90 }, { relativeDay: 100 }]
    .map(time => ({ ...time, relativeDayOrigin: "first scan" }))
  const dated = syntheticVisits(relative.map((time, index) => ({ ...time, scanDate: ["2024-01-01", "2024-01-03", "2024-01-11"][index] })))
  const dateSvg = reportLogic.buildReportFigureSvg(dated)
  assert.deepEqual(trendCoordinates(dateSvg)[0].map(point => point.x), [70, 170, 570])
  assert.match(dateSvg, /X-axis basis: Scan date/)
  const daySvg = reportLogic.buildReportFigureSvg(dated.map((point, index) => ({ ...point, scanDate: index === 0 ? point.scanDate : null })))
  assert.deepEqual(trendCoordinates(daySvg)[0].map(point => point.x), [70, 520, 570])
  assert.ok(axisTicks(daySvg).every(tick => /^Day /.test(tick.label)))
})

test("same-day visits share one x coordinate, and single visits remain visible", () => {
  for (const count of [1, 2]) {
    const rows = syntheticVisits(Array.from({ length: count }, () => ({ relativeDay: 0, relativeDayOrigin: "first scan" })))
    const svg = reportLogic.buildReportFigureSvg(rows)
    assert.deepEqual(trendCoordinates(svg)[0].map(point => point.x), Array(count).fill(320))
    assert.equal(axisTicks(svg).length, count)
    assert.equal(Array.from(svg.matchAll(/<circle[^>]+r="4"/g)).length, count * 2)
    assert.doesNotMatch(svg, /NaN|Infinity/)
  }
})

test("local exports preserve fractional day and origin metadata without manufacturing dates", () => {
  const rows = syntheticVisits([0, 56.40625, 56.46180555555475].map(relativeDay => ({ relativeDay, relativeDayOrigin: "first scan", intervalDays: relativeDay, daysFromReference: relativeDay })))
  const html = reportLogic.buildHtmlMeasurementRows(rows, rows[1].id)
  const text = reportLogic.buildReportExportText("Synthetic", "Visit 2", "pending", [], rows[1], null, rows)
  for (const output of [html, text]) {
    assert.match(output, /Scan date: Unknown/)
    assert.match(output, /Relative day: Day 0/)
    assert.match(output, /Relative day: Day 56\.4/)
    assert.match(output, /Relative day: Day 56\.5/)
    assert.match(output, /Relative day origin: first scan/)
    assert.doesNotMatch(output, /56\.40625|56\.461805/)
  }
  assert.match(text, /Scan: Day 56\.4/)
  assert.match(reportLogic.buildReportExportText("Synthetic", "Visit 2", "pending", [], rows[1], null), /Relative day: Day 56\.4/)
  const payload = reportLogic.buildReportPayload("Synthetic", "Visit 2", "pending", [], rows[1], rows, null)
  assert.equal(payload.date, "Day 56.4")
  assert.equal(payload.active_measurements.relative_day, 56.40625)
  assert.equal(payload.active_measurements.interval_days, 56.40625)
  assert.equal(payload.active_measurements.days_from_reference, 56.40625)
  const csv = reportLogic.buildMeasurementsCsv(rows).split("\n").map(line => line.split(","))
  rows.forEach((row, index) => {
    assert.equal(payload.timepoints[index].scan_date, null)
    assert.equal(payload.timepoints[index].relative_day, row.relativeDay)
    assert.equal(payload.timepoints[index].relative_day_origin, "first scan")
    assert.equal(csv[index + 1][csv[0].indexOf("scan_date")], "")
    assert.equal(csv[index + 1][csv[0].indexOf("relative_day")], String(row.relativeDay))
    assert.equal(csv[index + 1][csv[0].indexOf("relative_day_origin")], "first scan")
    assert.equal(csv[index + 1][csv[0].indexOf("interval_days_since_previous_visit")], String(row.intervalDays))
  })
})

test("unknown and invalid relative days stay unavailable, while local metadata is escaped", () => {
  for (const relativeDay of [undefined, null, NaN, Infinity, "56.4"]) {
    const row = syntheticVisits([{ relativeDay, relativeDayOrigin: null }])[0]
    assert.equal(reportLogic.measurementPayload(row).relative_day, null)
    assert.equal(reportLogic.measurementPayload(row).relative_day_origin, null)
    assert.match(reportLogic.buildVisitTimingText([row]), /Relative day: Unknown; Relative day origin: Unknown/)
    const [header, values] = reportLogic.buildMeasurementsCsv([row]).split("\n").map(line => line.split(","))
    assert.equal(values[header.indexOf("relative_day")], "")
    assert.equal(values[header.indexOf("relative_day_origin")], "")
  }
  const row = syntheticVisits([{ relativeDay: -2.75, relativeDayOrigin: 'first <scan>, "synthetic"' }])[0]
  const html = reportLogic.buildHtmlMeasurementRows([row])
  assert.match(html, /Day -2\.8/)
  assert.match(html, /first &lt;scan&gt;, &quot;synthetic&quot;/)
  assert.doesNotMatch(html, /<scan>/)
  assert.match(reportLogic.buildMeasurementsCsv([row]), /"first <scan>, ""synthetic"""/)
  assert.equal(reportLogic.measurementPayload(row).relative_day, -2.75)
})
