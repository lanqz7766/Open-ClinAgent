// Cornerstone can still be attaching actors after a React effect is cancelled.
// Let that work settle before disposing its engine, without publishing stale UI.
export function startViewerSetup(
  setup: (isCancelled: () => boolean) => Promise<void>,
  dispose: () => void,
  onError: (error: unknown) => void,
) {
  let cancelled = false
  let settled = false
  let disposed = false
  const release = () => {
    if (disposed) return
    disposed = true
    dispose()
  }
  const completion = (async () => {
    try {
      await setup(() => cancelled)
    } catch (error) {
      release()
      if (!cancelled) onError(error)
    } finally {
      settled = true
      if (cancelled) release()
    }
  })()
  return {
    completion,
    cancel() {
      cancelled = true
      if (settled) release()
    },
  }
}

export async function loadViewerImages(
  imageIds: string[],
  loadImage: (imageId: string) => Promise<unknown>,
  isCancelled: () => boolean,
) {
  if (!imageIds.length || isCancelled()) return
  // A NIfTI's first frame fetches/decodes the file shared by its other frames.
  await loadImage(imageIds[0])
  if (isCancelled()) return
  await Promise.all(imageIds.slice(1).map(loadImage))
}
