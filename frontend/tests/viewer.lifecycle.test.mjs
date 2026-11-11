import assert from "node:assert/strict"
import test from "node:test"
import { readFileSync } from "node:fs"
import { loadViewerImages, startViewerSetup } from "../src/lib/viewerLifecycle.ts"

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test("cancel during actor attachment defers disposal and never publishes stale readiness", async () => {
  const attaching = deferred()
  const events = []
  const session = startViewerSetup(async (cancelled) => {
    events.push("attaching")
    await attaching.promise
    if (!cancelled()) events.push("ready")
  }, () => events.push("disposed"), () => events.push("error"))
  session.cancel()
  assert.deepEqual(events, ["attaching"])
  attaching.resolve()
  await session.completion
  session.cancel()
  assert.deepEqual(events, ["attaching", "disposed"])
})

test("late Original/Aligned completions cannot dispose or mark the final Original ready", async () => {
  const events = []
  const runs = ["original-1", "aligned", "original-2"].map((id) => {
    const data = deferred()
    const session = startViewerSetup(async (cancelled) => {
      await data.promise
      if (!cancelled()) events.push(`ready:${id}`)
    }, () => events.push(`dispose:${id}`), () => events.push(`error:${id}`))
    return { data, session }
  })
  runs[0].session.cancel()
  runs[1].session.cancel()
  runs[2].data.resolve()
  await runs[2].session.completion
  runs[1].data.reject(new Error("obsolete request"))
  runs[0].data.resolve()
  await Promise.all(runs.map(({ session }) => session.completion))
  assert.deepEqual(events, ["ready:original-2", "dispose:aligned", "dispose:original-1"])
  runs[2].session.cancel()
  assert.equal(events.at(-1), "dispose:original-2")
})

test("active failures dispose before reporting the fallback, once", async () => {
  const events = []
  const session = startViewerSetup(async () => { throw new Error("MRI failed") },
    () => events.push("disposed"), (error) => events.push(error.message))
  await session.completion
  session.cancel()
  assert.deepEqual(events, ["disposed", "MRI failed"])
})

test("pixel loading waits for all frames, not a void volume.load return", async () => {
  const first = deferred(), last = deferred()
  const calls = []
  let ready = false
  const loading = loadViewerImages(["first", "last"], (id) => {
    calls.push(id)
    return id === "first" ? first.promise : last.promise
  }, () => false).then(() => { ready = true })
  assert.deepEqual(calls, ["first"])
  first.resolve()
  await Promise.resolve()
  assert.deepEqual(calls, ["first", "last"])
  assert.equal(ready, false)
  last.resolve()
  await loading
  assert.equal(ready, true)
})

test("cancelled first frame does not enqueue the rest of an obsolete volume", async () => {
  const first = deferred()
  let cancelled = false
  const calls = []
  const loading = loadViewerImages(["first", "last"], (id) => {
    calls.push(id)
    return first.promise
  }, () => cancelled)
  cancelled = true
  first.resolve()
  await loading
  assert.deepEqual(calls, ["first"])
})

test("asset-pair changes isolate viewports and dispose GPU volumes without purging shared pixels", () => {
  const source = readFileSync(new URL("../src/components/CornerstoneStructuralViewer.tsx", import.meta.url), "utf8")
  // Only the segmentation and layout remount the session; anatomy volumes swap in place.
  assert.match(source, /JSON\.stringify\(\[props\.segmentationAssetUrl, props\.panels\?\.map\(\(panel\) => \[panel\.id, panel\.plane\]\) \?\? "mpr"\]\)/)
  assert.match(source, /CornerstoneViewerSession key=\{assetKey\}/)
  assert.match(source, /useEffectEvent\(onInitializationError\)/)
  assert.match(source, /loadViewerImages\(imageIds, \(id\) => imageLoader\.loadAndCacheImage\(id\), dropped\)/)
  assert.match(source, /cache\.removeVolumeLoadObject\(volumeId\)/)
  const disposal = source.slice(source.indexOf("startViewerSetup(setup,"))
  assert.ok(disposal.indexOf("ownedEngine?.destroy()") < disposal.indexOf("segmentation.removeSegmentation(segmentationId)"))
  assert.doesNotMatch(source, /await .*Volume\??\.load|cache\.purgeCache/)
})

test("comparison panels carry their own overlay and window while sharing camera and crosshair", () => {
  const source = readFileSync(new URL("../src/components/CornerstoneStructuralViewer.tsx", import.meta.url), "utf8")
  // Every panel receives the labelmap; visibility is decided per panel.
  assert.doesNotMatch(source, /key !== "original"/)
  assert.match(source, /const overlayVisible = overlayVisibleFor\(key\)/)
  assert.match(source, /\(panelById\.get\(key\)\?\.showOverlay \?\? showOverlay\) && !hideOverlayTemporarily/)
  // Each panel may use its own outline/fill style.
  assert.match(source, /labelmapStyleFor\(mode\)/)
  assert.match(source, /panelById\.get\(key\)\?\.overlayMode \?\? viewerMode/)
  // Same-plane panels share the camera; other planes jump to the focal point.
  const sync = source.slice(source.indexOf("const syncFromViewport"), source.indexOf("const onCameraModified"))
  assert.match(sync, /if \(other\.plane === view\.plane\)/)
  assert.match(sync, /target\.setCamera\(camera\)/)
  assert.match(sync, /target\.jumpToWorld\(focal\)/)
  // Window/level follows only between panels that show the same volume.
  assert.match(sync, /anatomySession\.loadedUrls\[view\.key\] === anatomySession\.loadedUrls\[other\.key\]/)
  assert.match(sync, /target\.setProperties\(\{ voiRange, invert \}\)/)
  assert.match(source, /csEnums\.Events\.VOI_MODIFIED/)
  assert.match(source, /if \(syncingRef\.current\) return/)
  assert.match(source, /setVisibility\?\.\(!overlayVisible \|\| mode !== "mask"\)/)
  assert.match(source, /sliceCounts\.some\(\(count\) => !Number\.isFinite\(count\) \|\| count <= 0\)/)
  assert.doesNotMatch(source, /currentImageIds\.every/)
})

test("a panel modality change swaps its volume in place and releases the volume it replaced", () => {
  const source = readFileSync(new URL("../src/components/CornerstoneStructuralViewer.tsx", import.meta.url), "utf8")
  const swap = source.slice(source.indexOf("// Swap anatomy volumes in place"), source.indexOf("const style ="))
  // The swap never tears down the engine or resets readiness, so the other panels keep their state.
  assert.doesNotMatch(swap, /setViewerReady\(false\)|new RenderingEngine|destroy\(\)/)
  assert.ok(swap.indexOf("const camera = viewport.getCamera()") < swap.indexOf("await viewport.setVolumes("))
  assert.ok(swap.indexOf("await viewport.setVolumes(") < swap.indexOf("viewport.setCamera(camera)"))
  assert.match(swap, /triggerSegmentationRender\(viewportIdFor\(key\)\)/)
  assert.match(swap, /registry\.get\(previousUrl\)\?\.users\.delete\(key\)/)
  assert.match(swap, /collectUnusedVolumes\(anatomySession\)/)
  // Volumes belong to one setup run so a superseded run cannot release the live run's volumes.
  assert.match(source, /`cornerstone-volume-\$\{reactId\}-\$\{session\.nonce\}-anatomy-/)
  assert.match(source, /releaseAllVolumes\(anatomySession\)/)
})

test("temporary MRI preview changes visibility without reloading assets or changing saved overlay settings", () => {
  const source = readFileSync(new URL("../src/components/CornerstoneStructuralViewer.tsx", import.meta.url), "utf8")
  assert.match(source, /&& !hideOverlayTemporarily/)
  assert.match(source, /const overlayVisible = overlayVisibleFor\(key\)/)
  assert.match(source, /overlayVisible && effectiveVisibleLabels.has\(label.labelId\)/)
  const setup = source.slice(source.indexOf("async function setup"), source.indexOf("const style ="))
  assert.doesNotMatch(setup, /hideOverlayTemporarily/)
  assert.match(source, /setVisibility\?\.\(!overlayVisible \|\| mode !== "mask"\)/)
})
