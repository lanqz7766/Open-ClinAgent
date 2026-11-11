import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import test from "node:test"
import vm from "node:vm"
import React from "react"
import { renderToStaticMarkup } from "react-dom/server"
import ts from "typescript"

const timing = {}
vm.createContext(timing)
vm.runInContext(ts.transpile(readFileSync(new URL("../src/pages/analysis/brainTumor.timing.ts", import.meta.url), "utf8").replaceAll("export ", ""), { target: ts.ScriptTarget.ES2022 }), timing)

const source = ts.createSourceFile(
  "BrainTumorPage.tsx",
  readFileSync(new URL("../src/pages/analysis/BrainTumorPage.tsx", import.meta.url), "utf8"),
  ts.ScriptTarget.Latest,
  true,
  ts.ScriptKind.TSX,
)

function findJsx(tag) {
  const found = []
  function visit(node) {
    if ((ts.isJsxSelfClosingElement(node) || ts.isJsxOpeningElement(node)) && node.tagName.getText(source) === tag) found.push(node)
    ts.forEachChild(node, visit)
  }
  visit(source)
  return found
}

function ancestors(node) {
  const parents = []
  for (let parent = node.parent; parent; parent = parent.parent) parents.push(parent)
  return parents
}

function hasAttribute(node, name, value) {
  if (!ts.isJsxElement(node)) return false
  return node.openingElement.attributes.properties.some((attr) =>
    ts.isJsxAttribute(attr) && attr.name.getText(source) === name && attr.initializer &&
    ts.isStringLiteral(attr.initializer) && attr.initializer.text === value,
  )
}

test("the MRI viewer is shared, never mounted by a results tab", () => {
  const viewers = findJsx("CornerstoneStructuralViewer")
  assert.equal(viewers.length, 1)
  const parents = ancestors(viewers[0])
  assert.ok(parents.some((node) => hasAttribute(node, "aria-label", "Imaging workstation")))
  assert.ok(!parents.some((node) => hasAttribute(node, "role", "tabpanel")))
  assert.ok(!parents.some((node) => ts.isConditionalExpression(node) && node.condition.getText(source).includes("activeWorkspaceTab")))
})

test("alignment workflow stays with the MRI across results tabs", () => {
  const panel = findJsx("BrainTumorAlignment")
  assert.equal(panel.length, 1)
  assert.ok(ancestors(panel[0]).some((node) => hasAttribute(node, "aria-label", "Imaging workstation")))
  assert.ok(!ancestors(panel[0]).some((node) => hasAttribute(node, "role", "tabpanel")))
  const page = source.getFullText()
  assert.match(page, /bias_correction: biasCorrection/)
  assert.match(page, /signal\.throwIfAborted\(\)/)
  assert.match(page, /baseline_session_id === baselinePoint\?\.sessionId/)
})

function alignmentMarkup(props) {
  const file = ts.createSourceFile("alignment.tsx", readFileSync(new URL("../src/pages/analysis/BrainTumorAlignment.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const body = file.statements.filter((node) => !ts.isImportDeclaration(node)).map((node) => node.getText(file)).join("\n")
  const icons = Object.fromEntries(["Check", "ChevronDown", "Crosshair", "FileCheck2", "Layers", "Loader2", "Minus", "Move3D", "ScanLine", "SlidersHorizontal", "X"].map((name) => [name, "svg"]))
  const context = { exports: {}, React, useState: React.useState, cn: (...parts) => parts.filter(Boolean).join(" "), ...icons }
  vm.createContext(context)
  vm.runInContext(ts.transpile(body, { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, module: ts.ModuleKind.CommonJS }), context)
  return renderToStaticMarkup(React.createElement(context.exports.BrainTumorAlignment, {
    job: null, points: [{ sessionId: "moving", dateLabel: "Day 40" }], referenceLabel: "Day 10",
    busy: false, error: null, activeSessionId: "moving", ...props,
  }))
}

test("alignment shows actual skipped steps and excludes the reference from follow-up counts", () => {
  const html = alignmentMarkup({ job: { status: "completed", visits: [
    { session_id: "fixed", status: "reference" },
    { session_id: "moving", status: "complete", registration: { ncc_delta: 0.042, registration_runtime_sec: 44.5 }, steps: [
      { id: "intensity", label: "Intensity correction", status: "skipped", detail: "N4 not selected" },
    ] },
  ] } })
  assert.match(html, /1\/1 follow-ups/)
  assert.match(html, /N4 not selected/)
  assert.match(html, /Not applied/)
  assert.match(html, /\+0\.042/)
  assert.match(html, /Day 40/)
})

test("a failed rerun never presents previous alignment QC as its own result", () => {
  const html = alignmentMarkup({ registration: { ncc_delta: 0.5 }, job: { status: "completed_with_errors", visits: [
    { session_id: "moving", status: "failed", steps: [{ id: "within_visit", label: "Within-visit alignment", status: "failed" }] },
  ] } })
  assert.match(html, /Alignment needs attention/)
  assert.match(html, /0\/1 follow-ups/)
  assert.doesNotMatch(html, /NCC change|\+0\.500/)
  assert.doesNotMatch(alignmentMarkup({ busy: true }), /follow-ups|NCC change/)
})

test("workspace tabs control only the results region, not the case library or MRI", () => {
  const navs = findJsx("BrainTumorWorkspaceNav")
  assert.equal(navs.length, 1)
  const parents = ancestors(navs[0])
  assert.ok(parents.some((node) => hasAttribute(node, "aria-label", "Case results")))
  assert.ok(!parents.some((node) => hasAttribute(node, "aria-label", "Imaging workstation")))
  assert.ok(!parents.some((node) => hasAttribute(node, "aria-label", "Case library")))
})

test("visit navigation stays above the shared MRI and changes viewing, never the reference", () => {
  const navs = findJsx("BrainTumorVisitNavigator")
  assert.equal(navs.length, 1)
  const parents = ancestors(navs[0])
  assert.ok(parents.some((node) => hasAttribute(node, "aria-label", "Imaging workstation")))
  assert.ok(!parents.some((node) => hasAttribute(node, "role", "tabpanel")))
  assert.ok(navs[0].pos < findJsx("CornerstoneStructuralViewer")[0].pos)
  const attribute = (name) => navs[0].attributes.properties.find((attr) => attr.name?.getText(source) === name).initializer.expression.getText(source)
  assert.equal(attribute("onSelectActive"), "setActivePointId")
  assert.equal(attribute("points"), "longitudinalRows")
  assert.equal(attribute("activePointId"), 'activePoint?.id ?? ""')
  assert.equal(attribute("baselinePointId"), 'baselinePoint?.id ?? ""')
})

function visitNavigator(props = {}) {
  const node = source.statements.find((item) => ts.isFunctionDeclaration(item) && item.name?.text === "BrainTumorVisitNavigator")
  const context = { React, ...timing, cn: (...parts) => parts.filter(Boolean).join(" "), ChevronLeft: "svg", ChevronRight: "svg", Pin: "svg", Clock3: "svg", Eye: "svg" }
  vm.createContext(context)
  const summary = ts.createSourceFile("VisitTimingSummary.tsx", readFileSync(new URL("../src/pages/analysis/VisitTimingSummary.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const component = summary.statements.find(item => ts.isFunctionDeclaration(item))
  vm.runInContext(ts.transpile(component.getText(summary).replace("export ", ""), { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React }), context)
  vm.runInContext(ts.transpile(node.getText(source), { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React }), context)
  return context.BrainTumorVisitNavigator({
    activePointId: "scan-1", baselinePointId: "scan-1", samePatientLongitudinal: true,
    points: Array.from({ length: 6 }, (_, index) => ({ id: `scan-${index + 1}`, label: `Patient A Visit ${index + 1}`, dateLabel: `Timepoint ${index + 1}` })),
    onSelectActive: () => {}, ...props,
  })
}

function elements(element, type) {
  if (!React.isValidElement(element)) return []
  return [ ...(element.type === type ? [element] : []), ...React.Children.toArray(element.props.children).flatMap((child) => elements(child, type)) ]
}

test("relative timing appears in navigation without inventing scan dates", () => {
  const points = timing.annotateVisitTiming([84,126,246].map((day,index) => ({id:`v${index}`,label:`Visit ${index+1}`,dateLabel:`Timepoint ${index+1}`,scanDate:null,relativeDay:day,relativeDayOrigin:"diagnosis"})), "v0")
  const html = renderToStaticMarkup(visitNavigator({points,activePointId:"v1",baselinePointId:"v0"}))
  assert.match(html,/Day 126 from diagnosis/)
  assert.match(html,/42 days/)
  assert.match(html,/Day 246/)
})

function trendChart(props = {}, inspectedId = null, mode = "hover") {
  const file = ts.createSourceFile("TumorTrendChart.tsx", readFileSync(new URL("../src/pages/analysis/TumorTrendChart.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const body = file.statements.filter(node => !ts.isImportDeclaration(node)).map(node => node.getText(file)).join("\n")
  const context = { exports: {}, React, ...timing, Eye: "svg", Pin: "svg", tumorPalette: {et:"red",wt:"blue"},
    Popover: {Root:({children})=>children,Anchor:()=>null,Portal:({children})=>children,Content:({children,role,id})=>React.createElement("aside",{role,id},children)},
    formatMm3: value => `${value} mm³`, formatCompactMm3: String,
    useRef: () => ({current:null}), useState: initial => [initial === null && inspectedId ? {id:inspectedId,x:200,y:80,mode} : initial, () => {}], useLayoutEffect: () => {}, useEffect: () => {} }
  vm.createContext(context)
  vm.runInContext(ts.transpile(readFileSync(new URL("../src/pages/analysis/brainTumor.chartLayout.ts", import.meta.url), "utf8").replaceAll("export ", ""), { target: ts.ScriptTarget.ES2022 }), context)
  vm.runInContext(ts.transpile(body, {target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React,module:ts.ModuleKind.CommonJS}),context)
  return context.exports.TumorTrendChart({activePointId:"0",baselinePointId:"0",onSelectActive(){},...props})
}

test("compact and responsive main trend coordinates share the actual-time scale", () => {
  const context = {React,...timing,formatMm3:String}
  vm.createContext(context)
  for (const name of ["RanoTrendPreview"]) {
    const node = source.statements.find(item=>ts.isFunctionDeclaration(item) && item.name?.text===name)
    vm.runInContext(ts.transpile(node.getText(source),{target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.React}),context)
  }
  const points=[0,10,100].map((day,index)=>({id:String(index),relativeDay:day,relativeDayOrigin:"first scan",etMl:10,flairMl:30}))
  const compact=context.RanoTrendPreview({points,values:[10,20,30],color:"blue",label:"CE",activeIndex:-1})
  assert.deepEqual(elements(compact,"circle").map(node=>node.props.cx),[10,40,310])
  const main=trendChart({points})
  assert.deepEqual(elements(main,"circle").filter(node=>node.props["data-series"]==="etMl").map(node=>node.props.cx),[52,117.2,704])
  assert.match(renderToStaticMarkup(compact),/Days from first scan/)
})

test("trend points select visits by pointer and keyboard without changing the reference", () => {
  const changes = []
  const rows = [0,40].map((relativeDay,i)=>({id:i?"b":"a",relativeDay,relativeDayOrigin:"first scan",etMl:10,flairMl:20}))
  const chart = trendChart({points:rows,onSelectActive:id=>changes.push(id)})
  const targets = elements(chart,"g").filter(node=>node.props.role==="button")
  targets[1].props.onClick({stopPropagation(){}})
  targets[0].props.onKeyDown({key:"Enter",preventDefault(){}})
  targets[1].props.onKeyDown({key:" ",preventDefault(){}})
  assert.deepEqual(changes,["b","a","b"])
  assert.equal(targets.length,rows.length)
  assert.equal(elements(chart,"g").find(node=>node.props.pointerEvents==="none").props.pointerEvents,"none")
})

test("unified detail shows each volume once and updates reference offsets without shifting points", () => {
  const input=[0,40,100].map((relativeDay,i)=>({id:String(i),dateLabel:"",relativeDay,relativeDayOrigin:"first scan",etMl:123,flairMl:456}))
  const before = trendChart({points:timing.annotateVisitTiming(input,"0"),activePointId:"1"},"1")
  const after = trendChart({points:timing.annotateVisitTiming(input,"2"),activePointId:"1",baselinePointId:"2"},"1")
  const html=renderToStaticMarkup(after)
  assert.equal((html.match(/123 mm³/g)||[]).length,1)
  assert.equal((html.match(/456 mm³/g)||[]).length,1)
  assert.match(html,/40 days/)
  assert.match(html,/60 days before/)
  assert.match(html,/data-viewing-marker/)
  assert.match(html,/data-reference-marker/)
  assert.deepEqual(elements(before,"circle").map(n=>n.props.cx),elements(after,"circle").map(n=>n.props.cx))
})

test("only proximity to a line or endpoint inspects; blank plot space does not select", () => {
  const selections = [], inspections = []
  const points = [91,154,158,290].map((relativeDay,i)=>({id:String(i),relativeDay,relativeDayOrigin:"diagnosis",etMl:10,flairMl:20}))
  const chart = trendChart({points,onSelectActive:id=>selections.push(id),onInspect:id=>inspections.push(id)})
  const svg = elements(chart,"svg").find(node=>node.props.role==="group")
  const event=(x,y)=>({clientX:x,clientY:y,pointerType:"mouse",currentTarget:{getBoundingClientRect:()=>({left:0,top:0,width:720,height:svg.props.height})}})
  assert.equal(renderToStaticMarkup(chart).includes('role="tooltip"'),false)
  svg.props.onPointerMove(event(52,80)) // Same column as Visit 1, away from both lines.
  assert.deepEqual(inspections,[])
  svg.props.onPointerMove(event(52,133)) // CE endpoint.
  svg.props.onPointerMove(event(52,36)) // FLAIR endpoint.
  svg.props.onPointerMove(event(400,36)) // FLAIR line, near Visit 3.
  assert.deepEqual(inspections,["0","0","2"])
  svg.props.onClick(event(52,80))
  assert.deepEqual(selections,[])
  svg.props.onClick(event(52,133))
  assert.deepEqual(selections,["0"])
  svg.props.onPointerDown(event(400,80))
  svg.props.onClick(event(52,133))
  assert.deepEqual(selections,["0"],"Dragging across the plot must not select a scan")
})

test("keyboard focus opens detail, pointer focus does not, and Escape or leaving clears hover", () => {
  const selections = [], inspections = []
  const points = [0,40].map((relativeDay,i)=>({id:String(i),relativeDay,relativeDayOrigin:"diagnosis",etMl:10,flairMl:20}))
  const chart = trendChart({points,onSelectActive:id=>selections.push(id),onInspect:id=>inspections.push(id)},"0")
  const targets = elements(chart,"g").filter(node=>node.props.role==="button")
  targets[1].props.onFocus({currentTarget:{matches:()=>false}})
  assert.deepEqual(inspections,[])
  targets[1].props.onFocus({currentTarget:{matches:()=>true}})
  assert.deepEqual(inspections,["1"])
  assert.deepEqual(selections,[])
  const container=elements(chart,"div").find(node=>node.props.className==="tumor-trend")
  container.props.onKeyDown({key:"Escape"})
  container.props.onBlur({currentTarget:{contains:()=>false},relatedTarget:null})
  elements(chart,"svg").find(node=>node.props.role==="group").props.onPointerLeave()
  assert.deepEqual(inspections.slice(1),[null,null,null])
})

test("click-pinned detail is not replaced by passive pointer movement", () => {
  const inspections=[]
  const points=[0,40].map((relativeDay,i)=>({id:String(i),relativeDay,relativeDayOrigin:"diagnosis",etMl:10,flairMl:20}))
  const chart=trendChart({points,onInspect:id=>inspections.push(id)},"0","pinned")
  const svg=elements(chart,"svg").find(node=>node.props.role==="group")
  svg.props.onPointerMove({pointerType:"mouse"})
  svg.props.onPointerLeave()
  assert.deepEqual(inspections,[])
})

test("inspected endpoints, guide and label share one visit while viewing stays unchanged", () => {
  const points=[91,154,158,290].map((relativeDay,i)=>({id:String(i),relativeDay,relativeDayOrigin:"diagnosis",etMl:i+1,flairMl:20}))
  const normal=trendChart({points})
  const hovered=trendChart({points},"2")
  const groups=elements(hovered,"g")
  assert.deepEqual(groups.filter(n=>n.props["data-inspected-point"]).map(n=>n.props["data-inspected-point"]),["2","2"])
  assert.equal(groups.find(n=>n.props["data-inspected-guide"]).props["data-inspected-guide"],"2")
  assert.deepEqual(groups.filter(n=>n.props["data-inspected"]===true).map(n=>n.props["aria-label"]),["View visit 3, Day 158"])
  assert.equal(groups.find(n=>n.props["aria-pressed"]===true).props["aria-label"],"View visit 1, Day 91")
  const coordinates = tree => elements(tree,"circle").filter(n=>n.props["data-visit-point"]).map(n=>[n.props.cx,n.props.cy,n.props.r])
  assert.deepEqual(coordinates(normal),coordinates(hovered))
  assert.ok(coordinates(normal).every(n=>n[2]>=5))
})

test("visit buttons, arrows and compact selector select the exact scan ID", () => {
  const changes = []
  const element = visitNavigator({ activePointId: "scan-3", onSelectActive: (id) => changes.push(id) })
  const buttons = elements(element, "button")
  assert.equal(buttons.length, 8)
  assert.equal(buttons.filter((button) => button.props["aria-pressed"]).length, 1)
  assert.equal(buttons[3].props["aria-pressed"], true)
  buttons[0].props.onClick()
  buttons[7].props.onClick()
  buttons[6].props.onClick()
  const select = elements(element, "select")[0]
  assert.equal(select.props.value, "scan-3")
  select.props.onChange({ currentTarget: { value: "scan-5" } })
  assert.deepEqual(changes, ["scan-2", "scan-4", "scan-6", "scan-5"])
  const html = renderToStaticMarkup(element)
  assert.match(html, /Viewing Visit 3 of 6/)
  assert.match(html, /Reference<\/dt><dd>Visit 1<span class="visit-timing-detail">Visit 1<\/span>/)
  assert.match(html, /aria-label="View visit 1, reference"/)
  assert.doesNotMatch(html, /Unknown|unavailable|Since previous visit/)
})

test("first and last visit cannot navigate past the series", () => {
  const changes = []
  for (const [id, index] of [["scan-1", 0], ["scan-6", 7], ["missing", 0], ["missing", 7]]) {
    const button = elements(visitNavigator({ activePointId: id, onSelectActive: (value) => changes.push(value) }), "button")[index]
    assert.equal(button.props.disabled, true)
    button.props.onClick()
  }
  assert.deepEqual(changes, [])
})

test("navigation distinguishes reference from viewing and does not invent visit dates", () => {
  const html = renderToStaticMarkup(visitNavigator({ baselinePointId: "scan-4", activePointId: "scan-2" }))
  assert.match(html, /Reference<\/dt><dd>Visit 4<span class="visit-timing-detail">Visit 4<\/span>/)
  assert.match(html, /aria-label="View visit 4, reference"/)
  assert.doesNotMatch(html, /<small>Timepoint/)
  // A curated label such as "Day 102" is shown verbatim but never parsed into dates or intervals.
  const dated = renderToStaticMarkup(visitNavigator({ points: [
    { id: "scan-1", label: "Patient A", dateLabel: "Day 102", stageLabel: "Early follow-up" },
    { id: "scan-2", label: "Patient A", dateLabel: "Day 194" },
  ] }))
  assert.match(dated, /<strong>Day 102<\/strong><span class="visit-timing-detail">Early follow-up<\/span>/)
  assert.match(dated, /<small>Day 194<\/small>/)
  assert.doesNotMatch(dated, /Scan date|Unknown|Interval|Since previous visit|days/)
  const unrelated = renderToStaticMarkup(visitNavigator({ samePatientLongitudinal: false }))
  assert.match(unrelated, /Scan 1 of 6/)
  assert.doesNotMatch(unrelated, /Reference|Alignment reference/)
})

test("empty and single-scan cases have no unusable visit controls", () => {
  assert.equal(visitNavigator({ points: [] }), null)
  const single = visitNavigator({ points: [{ id: "scan-1", label: "Upload", dateLabel: "Baseline" }] })
  assert.equal(elements(single, "button").length, 0)
  assert.equal(elements(single, "select").length, 0)
  assert.match(renderToStaticMarkup(single), /Visit 1 of 1/)
})

test("many visits use a bounded selector and narrow workstations show compact navigation", () => {
  const many = visitNavigator({ points: Array.from({ length: 12 }, (_, i) => ({ id: `scan-${i + 1}`, label: `Scan ${i + 1}` })) })
  assert.match(renderToStaticMarkup(many), /visit-controls-many/)
  assert.equal(elements(many, "option").length, 12)
  const css = readFileSync(new URL("../src/pages/analysis/brainTumor.workspace.css", import.meta.url), "utf8")
  assert.match(css, /@container \(max-width: 620px\)\s*\{\s*\.visit-options \{ display: none; \}\s*\.visit-select \{ display: block; \}/)
})

test("desktop gives MRI its own column and puts results directly below it", () => {
  const css = readFileSync(new URL("../src/pages/analysis/brainTumor.workspace.css", import.meta.url), "utf8")
  assert.match(css, /grid-template-areas:\s*"cases imaging"\s*"\. results"/)
  assert.match(css, /grid-template-columns:\s*248px minmax\(0, 1fr\)/)
  assert.match(css, /grid-template-columns:\s*272px minmax\(0, 1fr\)/)
  assert.match(css, /\.brain-tumor-case-list\s*\{[^}]*overflow-y:\s*auto/)
  for (const label of ["Case library", "Imaging workstation", "Case results"]) {
    const region = findJsx(label === "Case library" ? "aside" : "section").find((node) => hasAttribute(node.parent, "aria-label", label))
    assert.ok(region)
    assert.ok(!region.getText(source).includes("sticky"), `${label} must not independently shift on scroll`)
  }
})

test("manual case selection retires automatic resume before awaiting the load and ignores older replies", async () => {
  let loadFunction
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && node.name?.text === "runRegistryCase") loadFunction = node
    ts.forEachChild(node, visit)
  }
  visit(source)
  assert.ok(loadFunction)
  const state = {}
  const pending = new Map()
  const context = {
    registrySelectionRef: { current: "" },
    uploadSelectionRef: { current: "upload-current" },
    registryCases: [],
    rememberUploadSelection: (value) => { context.uploadSelectionRef.current = value },
    resetViewerModalities: () => {},
    fetch: (_url, options) => new Promise((resolve) => pending.set(JSON.parse(options.body).case_id, resolve)),
  }
  for (const match of loadFunction.getText(source).matchAll(/\b(set\w+)\(/g)) {
    context[match[1]] = (value) => { state[match[1]] = typeof value === "function" ? value(state[match[1]]) : value }
  }
  vm.createContext(context)
  vm.runInContext(ts.transpile(loadFunction.getText(source), { target: ts.ScriptTarget.ES2022 }), context)
  const old = context.runRegistryCase("case-old")
  assert.equal(state.setSegmentResumeChecked, true)
  assert.equal(context.registrySelectionRef.current, "case-old")
  const latest = context.runRegistryCase("case-new")
  const response = (id) => ({ ok: true, json: async () => ({ ok: true, same_patient_longitudinal: true, points: [{ id, label: id, volumes: [] }] }) })
  pending.get("case-new")(response("scan-new"))
  await latest
  pending.get("case-old")(response("scan-old"))
  await old
  assert.equal(state.setActiveRegistryCaseId, "case-new")
  assert.equal(state.setActivePointId, "scan-new")
  assert.equal(state.setLongitudinalPoints[0].id, "scan-new")
  assert.equal(state.setRunningRegistryCaseId, "")
})

test("measurement details are expanded on first render", () => {
  const detail = findJsx("details").find((node) => node.parent.getText(source).includes("Measurement details"))
  assert.ok(detail)
  assert.ok(detail.attributes.properties.some((attr) => ts.isJsxAttribute(attr) && attr.name.getText(source) === "open" && !attr.initializer))
})

function initialCaseContext(overrides = {}) {
  const names = new Set(["selectDefaultRegistryCase", "compareRegistryCasesForPicker", "registryCasePickerScore", "isRunnableRegistryCase", "openInitialRegistryCase", "resumeUploadJob"])
  const functions = []
  function visit(node) {
    if (ts.isFunctionDeclaration(node) && names.has(node.name?.text)) functions.push(node.getText(source))
    ts.forEachChild(node, visit)
  }
  visit(source)
  const loaded = []
  const context = {
    requiredModalities: ["t1n", "t1c", "t2w", "t2f"],
    registryCases: [], uploadedCases: [],
    registrySelectionRef: { current: "" }, uploadSelectionRef: { current: "" },
    fetch: async () => ({ ok: true, json: async () => ({ ok: true, job: null }) }),
    runRegistryCase: async (id) => { loaded.push(id); context.registrySelectionRef.current = id },
    setRunning: () => {}, setRegistrationError: (message) => assert.fail(message),
    applySegmentJobUpdate: () => {}, pollSegmentJob: async () => {},
    applyUploadJobUpdate: () => assert.fail("No completed job should replace the default"),
    openUploadedCase: () => assert.fail("No completed upload should be selected"),
    ...overrides,
  }
  vm.createContext(context)
  vm.runInContext(ts.transpile(functions.join("\n"), { target: ts.ScriptTarget.ES2022 }), context)
  return { context, loaded }
}

const sixVisitCase = (id, extra = {}) => ({
  id, title: id, timepoint_count: 6,
  demo_quality: { cache_count: 6 },
  timepoints: Array.from({ length: 6 }, () => ({ modalities: ["t1n", "t1c", "t2w", "t2f"] })),
  ...extra,
})

test("default case requires six complete visits with existing masks, not ground-truth labels", () => {
  const { context } = initialCaseContext()
  const available = [
    sixVisitCase("uncached", { demo_quality: { cache_count: 5, recommended: true } }),
    sixVisitCase("short", { timepoint_count: 3 }),
    sixVisitCase("missing-input", { timepoints: Array.from({ length: 6 }, () => ({ modalities: ["t1c"] })) }),
    sixVisitCase("mismatched-count", { timepoints: [] }),
    sixVisitCase("b"), sixVisitCase("a"),
  ]
  assert.equal(context.selectDefaultRegistryCase(available).id, "a")
  assert.equal(available[0].id, "uncached", "selection does not reorder the case list")
  assert.equal(context.selectDefaultRegistryCase(available.slice(0, 4)), undefined)
  assert.equal(context.selectDefaultRegistryCase([]), undefined)
})

test("fresh entry opens the six-visit case instead of a completed or failed job", async () => {
  for (const status of [null, "completed", "failed"]) {
    const { context, loaded } = initialCaseContext({
      registryCases: [sixVisitCase("default")],
      fetch: async () => ({ ok: true, json: async () => ({ ok: true, job: status ? { status, case_id: "old" } : null }) }),
    })
    await context.openInitialRegistryCase()
    assert.deepEqual(loaded, ["default"])
    await context.resumeUploadJob()
  }
})

test("an active job takes precedence over the default case", async () => {
  const applied = []
  const polled = []
  const { context, loaded } = initialCaseContext({
    registryCases: [sixVisitCase("default")],
    fetch: async () => ({ ok: true, json: async () => ({ ok: true, job: { status: "running", case_id: "active", job_id: "job" } }) }),
    applySegmentJobUpdate: (job) => applied.push(job.case_id),
    pollSegmentJob: async (id) => polled.push(id),
  })
  await context.openInitialRegistryCase()
  assert.deepEqual(loaded, ["active"])
  assert.deepEqual(applied, ["active"])
  assert.deepEqual(polled, ["job"])
})

test("an upload link or manual selection wins over a late initial-case response", async () => {
  for (const selection of ["uploadSelectionRef", "registrySelectionRef"]) {
    let reply
    const { context, loaded } = initialCaseContext({
      registryCases: [sixVisitCase("default")],
      fetch: () => new Promise((resolve) => { reply = resolve }),
    })
    const opening = context.openInitialRegistryCase()
    context[selection].current = "chosen-case"
    reply({ ok: true, json: async () => ({ ok: true, job: null }) })
    await opening
    assert.deepEqual(loaded, [])
  }
  assert.match(source.getFullText(), /!uploadResumeComplete \|\| segmentResumeChecked/)
})

test("viewer labels start expanded with a reader-controlled disclosure", () => {
  const viewer = ts.createSourceFile("viewer.tsx", readFileSync(new URL("../src/components/CornerstoneStructuralViewer.tsx", import.meta.url), "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const dropdown = viewer.statements.find((node) => ts.isFunctionDeclaration(node) && node.name?.text === "CompactSegmentationLabelDropdown")
  const context = { React, useState: React.useState, useMemo: React.useMemo, Layers3: "svg", ChevronDown: "svg" }
  vm.createContext(context)
  vm.runInContext(ts.transpile(dropdown.getText(viewer), { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React }), context)
  const html = renderToStaticMarkup(React.createElement(context.CompactSegmentationLabelDropdown, {
    overlayModel: { labelById: {}, groups: [] }, visibleLabelIds: [], showOverlay: true,
  }))
  assert.match(html, /<details open=""/)
  assert.match(dropdown.getText(viewer), /onToggle=\{\(event\) => setLabelsExpanded\(event.currentTarget.open\)\}/)
})

test("bulk mapping rejects mixed visits and never changes the loaded MRI", () => {
  let node
  function visit(item) {
    if (ts.isFunctionDeclaration(item) && item.name?.text === "handleBulkNiftiUpload") node = item
    ts.forEachChild(item, visit)
  }
  visit(source)
  const state = {}
  const context = {
    isNiftiFileName: (name) => name.endsWith(".nii.gz"),
    inferModalityFromFileName: (name) => ({ modality: name.split(".")[0], reason: "name" }),
    modalityMeta: { t1n: { label: "T1" }, t1c: { label: "T1c" }, t2w: { label: "T2" }, t2f: { label: "FLAIR" } },
  }
  for (const match of node.getText(source).matchAll(/\b(set\w+)\(/g)) context[match[1]] = (value) => { state[match[1]] = value }
  vm.createContext(context)
  vm.runInContext(ts.transpile(node.getText(source), { target: ts.ScriptTarget.ES2022 }), context)
  const files = ["t1n", "t1c", "t2w", "t2f"].map((key) => ({ name: `${key}.nii.gz` }))
  context.handleBulkNiftiUpload([...files, ...files])
  assert.match(state.setError, /Multiple visits/)
  assert.equal(Object.keys(state.setFiles).length, 0)
  assert.equal(state.setDeidentifiedConfirmed, false)
  context.handleBulkNiftiUpload(files)
  assert.equal(Object.keys(state.setFiles).length, 4)
  assert.equal(state.setError, null)
  assert.equal(state.setSession, undefined)
  context.handleBulkNiftiUpload([{ name: "example.zip" }])
  assert.match(state.setError, /NIfTI ZIP/)
  assert.equal(Object.keys(state.setFiles).length, 0)
})

test("ZIP preparation clears stale mappings and ignores a cancelled or superseded extraction", async () => {
  let node
  function visit(item) {
    if (ts.isFunctionDeclaration(item) && item.name?.text === "prepareBulkNiftiUpload") node = item
    ts.forEachChild(item, visit)
  }
  visit(source)
  const state = {}
  const pending = []
  const mapped = []
  const context = {
    AbortController,
    archiveRequestRef: { current: null },
    handleBulkNiftiUpload: (files) => mapped.push(files),
    require: () => ({ prepareNiftiSelection: (_files, progress, signal) => new Promise((resolve) => pending.push({ resolve, progress, signal })) }),
  }
  for (const match of node.getText(source).matchAll(/\b(set\w+)\(/g)) context[match[1]] = (value) => { state[match[1]] = value }
  vm.createContext(context)
  vm.runInContext(ts.transpile(node.getText(source), { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS }), context)
  const first = context.prepareBulkNiftiUpload([{ name: "first.zip" }])
  await new Promise(setImmediate)
  assert.equal(Object.keys(state.setFiles).length, 0)
  assert.equal(state.setDeidentifiedConfirmed, false)
  const second = context.prepareBulkNiftiUpload([{ name: "second.zip" }])
  await new Promise(setImmediate)
  assert.equal(pending[0].signal.aborted, true)
  pending[1].progress({ phase: "ready", completed: 4, total: 4, percent: 100 })
  pending[1].resolve(["second-result"])
  await second
  pending[0].progress({ phase: "extracting" })
  pending[0].resolve(["obsolete-result"])
  await first
  assert.deepEqual(mapped, [["second-result"]])
  assert.equal(state.setArchiveProgress.phase, "ready")
  assert.equal(context.archiveRequestRef.current, null)
  const closed = context.prepareBulkNiftiUpload([{ name: "closed.zip" }])
  await new Promise(setImmediate)
  context.archiveRequestRef.current.abort()
  pending[2].resolve(["closed-result"])
  await closed
  assert.equal(mapped.length, 1)
})

test("upload mapping retains full file names and supports explicit removal without clearing on picker cancel", () => {
  const node = source.statements.find((item) => ts.isFunctionDeclaration(item) && item.name?.text === "FileInput")
  assert.ok(node)
  const changes = []
  const context = { React, visitTimingLabel: timing.visitTimingLabel, cn: (...parts) => parts.filter(Boolean).join(" "), Button: "button", FolderOpen: "svg", X: "svg" }
  vm.createContext(context)
  vm.runInContext(ts.transpile(node.getText(source), { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React }), context)
  const selectedFile = { name: `test_${"long_filename_".repeat(10)}_FLAIR.nii.gz`, size: 3 * 1024 * 1024 }
  const element = context.FileInput({ label: "FLAIR", selectedFile, onChange: (file) => changes.push(file) })
  const html = renderToStaticMarkup(element)
  assert.ok(html.includes(selectedFile.name))
  assert.ok(html.includes("overflow-wrap:anywhere"))
  assert.ok(html.includes('aria-label="Remove FLAIR file"'))
  const label = element.props.children[0]
  const input = label.props.children[0]
  const cancelled = { currentTarget: { files: [], value: "" } }
  input.props.onChange(cancelled)
  assert.equal(changes.length, 0)
  const replaced = { currentTarget: { files: [selectedFile], value: "chosen" } }
  input.props.onChange(replaced)
  assert.equal(changes[0], selectedFile)
  assert.equal(replaced.currentTarget.value, "")
  element.props.children[1].props.onClick()
  assert.equal(changes[1], null)
})

test("visit navigation renders exact synthetic scan dates and adjacent interval", () => {
  const points = timing.annotateVisitTiming([{ id: "scan-1", label: "Synthetic", dateLabel: "2024-02-29" }, { id: "scan-2", label: "Synthetic", dateLabel: "2024-03-01" }], "scan-1")
  const html = renderToStaticMarkup(visitNavigator({ points, activePointId: "scan-2" }))
  assert.match(html, /Scan date: 2024-03-01/)
  assert.match(html, /Since previous visit<\/dt><dd>1 day/)
  assert.match(html, /1d since prior/)
  assert.match(renderToStaticMarkup(visitNavigator({ points, activePointId: "scan-1" })), /First visit/)
})

test("summary distinguishes the previous interval from the selected reference, including a later reference", () => {
  const raw = [0, 40, 140].map((relativeDay, i) => ({id:`v${i}`,dateLabel:`Visit ${i+1}`,scanDate:null,relativeDay,relativeDayOrigin:"first scan"}))
  let points = timing.annotateVisitTiming(raw, "v0")
  let html = renderToStaticMarkup(visitNavigator({points,activePointId:"v2",baselinePointId:"v0"}))
  assert.match(html, /Since previous visit<\/dt><dd>100 days/)
  assert.match(html, /From reference<\/dt><dd>140 days after/)
  points = timing.annotateVisitTiming(raw, "v2")
  html = renderToStaticMarkup(visitNavigator({points,activePointId:"v1",baselinePointId:"v2"}))
  assert.match(html, /Since previous visit<\/dt><dd>40 days/)
  assert.match(html, /From reference<\/dt><dd>100 days before/)
  assert.match(html, /Visit 3 · Day 140/)
  assert.match(renderToStaticMarkup(visitNavigator({points,activePointId:"v2",baselinePointId:"v2"})), /Selected reference/)
})

test("three planes are the default and optional comparison panels retain alignment space labels", () => {
  const page = source.getFullText()
  assert.match(page, /\[reviewPlane, setReviewPlane\].*\("mpr"\)/)
  // Comparison panels are a configurable list: no panels in three-plane mode, one plane for all otherwise.
  assert.match(page, /reviewPlane === "mpr" \|\| !activeVolumeAssetUrl\s*\? undefined\s*: reviewPanels\.map/)
  assert.match(page, /plane: reviewPlane,/)
  assert.match(page, /if \(showingAligned\) parts\.push\("aligned"\)/)
  // Presets: the T1c + FLAIR pair and the five-panel axial row with outlined overlays.
  assert.match(page, /pair: \{\s*label: "T1c \+ FLAIR",[\s\S]*?panels: \[\{ modality: "t1c", overlay: "fill" \}, \{ modality: "t2f", overlay: "fill" \}\],/)
  // Layout is the first-level choice; a preset click leaves the three-plane view on the remembered plane.
  assert.match(page, /aria-label="Layout"/)
  assert.match(page, /if \(reviewPlane === "mpr"\) setReviewPlane\(comparisonPlane\)/)
  assert.match(page, /badge: modalityMeta\[panel\.modality\]\.label,/)
  assert.match(page, /\{ modality: "t1n", overlay: "off" \},\s*\{ modality: "t1c", overlay: "off" \},\s*\{ modality: "t1c", overlay: "outline" \},\s*\{ modality: "t2f", overlay: "off" \},\s*\{ modality: "t2f", overlay: "outline" \}/)
  assert.match(page, /overlayMode: panel\.overlay === "outline" \? "contour" : undefined/)
  const viewer = findJsx("CornerstoneStructuralViewer")[0].getText(source)
  assert.match(viewer, /panels=\{viewerPanels\}/)
  assert.match(viewer, /hideOverlayTemporarily=\{previewOriginal\}/)
  assert.match(viewer, /showOverlay=\{showVolumeOverlay\}/)
  const button = findJsx("HoldToViewMriButton")[0].getText(source)
  assert.match(button, /onPressedChange=\{setPreviewOriginal\}/)
  assert.match(button, /key=\{.*activeVolumeAssetUrl.*activeSegmentationAssetUrl.*reviewPlane/)
})
