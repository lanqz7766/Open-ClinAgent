export function validateUploadFiles(files: Array<{ name: string; size: number }>): string | null {
  if (files.length !== 4) return "Select one examination: exactly four NIfTI files. Multiple visits must not be combined in this upload."
  if (files.some((file) => !/\.nii(\.gz)?$/i.test(file.name))) return "Map four NIfTI files before submitting. ZIP files must finish extracting first."
  if (files.some((file) => !file.size)) return "One of the selected files is empty."
  if (files.some((file) => file.size > 350 * 1024 * 1024)) return "Each NIfTI file must be 350 MB or smaller."
  if (files.reduce((sum, file) => sum + file.size, 0) > 1024 * 1024 * 1024) return "The four NIfTI files must be 1 GB or smaller in total."
  if (new Set(files).size !== 4) return "The same file is assigned to more than one modality. Check the mapping."
  return null
}

export function sendUpload(body: FormData, onProgress: (percent: number) => void): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open("POST", "/api/demo/brain-tumor/uploads")
    xhr.withCredentials = true
    xhr.timeout = 10 * 60 * 1000
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round(event.loaded / event.total * 100))
    }
    xhr.upload.onload = () => onProgress(100)
    xhr.onerror = xhr.ontimeout = () => reject(new Error("Upload connection interrupted. Check My uploads before submitting again; the server may have received your files."))
    xhr.onload = () => {
      let payload
      try { payload = JSON.parse(xhr.responseText) } catch {
        reject(new Error("The server could not confirm the upload. Check My uploads before submitting again."))
        return
      }
      if (xhr.status < 200 || xhr.status >= 300 || payload.ok === false) {
        reject(new Error(payload.error || (xhr.status === 401 ? "Your session expired. Sign in again." : "The upload could not be prepared.")))
      } else resolve(payload)
    }
    xhr.send(body)
  })
}

export async function readUploadJob<T>(
  url: string,
  onReconnect: (reconnecting: boolean) => void,
  signal: AbortSignal,
  wait: (ms: number) => Promise<unknown> = (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    signal.throwIfAborted()
    let response: Response | undefined
    try {
      response = await fetch(url, { credentials: "include", signal })
      if (response.ok) {
        const payload = await response.json() as T
        onReconnect(false)
        return payload
      }
    } catch (error) {
      if (signal.aborted) throw error
    }
    if (response?.status === 401) throw new Error("Your session expired. Sign in again to recover the job.")
    if (response?.status === 404) throw new Error("This upload is no longer available.")
    if ((response && response.status < 500 && response.status !== 429) || attempt >= 5) {
      throw new Error("Status is temporarily unavailable. Reopen the case in My uploads to reconnect; do not upload it again.")
    }
    onReconnect(true)
    await wait(Math.min(1500 * 2 ** attempt, 10000))
  }
}
