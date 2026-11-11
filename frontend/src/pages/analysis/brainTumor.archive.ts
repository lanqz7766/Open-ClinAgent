import { BlobReader, ZipReader } from "@zip.js/zip.js"
import type { FileEntry } from "@zip.js/zip.js"

export type ArchiveProgress = {
  phase: "reading" | "extracting" | "ready"
  completed: number
  total: number
  percent: number
}

const maxFileBytes = 350 * 1024 * 1024
const maxTotalBytes = 1024 * 1024 * 1024
const isNifti = (name: string) => /\.nii(\.gz)?$/i.test(name)

class ArchiveInputError extends Error {}

/** Expand locally, retaining relative paths so visits can be grouped before upload. */
export async function prepareNiftiSelection(
  selected: File[],
  onProgress: (progress: ArchiveProgress) => void,
  signal: AbortSignal,
): Promise<File[]> {
  signal.throwIfAborted()
  const archives = selected.filter((file) => /\.zip$/i.test(file.name))
  if (!archives.length) return selected
  if (selected.length !== 1) throw new ArchiveInputError("Choose one ZIP or a set of NIfTI files, not both.")
  const archive = archives[0]
  if (!archive.size) throw new ArchiveInputError("The ZIP file is empty.")
  if (archive.size > maxTotalBytes) throw new ArchiveInputError("The ZIP file must be 1 GB or smaller.")
  onProgress({ phase: "reading", completed: 0, total: 0, percent: 0 })
  const reader = new ZipReader(new BlobReader(archive))
  try {
    const candidates: FileEntry[] = []
    const names = new Set<string>()
    let entryCount = 0
    let expectedBytes = 0
    for await (const entry of reader.getEntriesGenerator()) {
      signal.throwIfAborted()
      if (++entryCount > 256) throw new ArchiveInputError("This ZIP contains too many entries. Choose up to six visits, with four NIfTI files per visit.")
      const parts = entry.filename.replaceAll("\\", "/").split("/")
      if (entry.directory || parts.some((part) => part === "__MACOSX" || (part.startsWith(".") && part !== ".."))) continue
      if (!isNifti(entry.filename)) continue
      if (parts.includes("..") || !parts[0] || /^[a-z]:/i.test(parts[0])) throw new ArchiveInputError("The ZIP contains an invalid file path. Repackage the four NIfTI files.")
      if (entry.encrypted) throw new ArchiveInputError("Password-protected ZIP files are not supported. Use an unencrypted ZIP.")
      const name = parts.join("/").toLowerCase()
      if (names.has(name)) throw new ArchiveInputError("Duplicate NIfTI paths found. Keep each visit in a separate folder.")
      names.add(name)
      candidates.push(entry)
      if (candidates.length > 24) throw new ArchiveInputError("A ZIP can contain up to six visits, with four NIfTI files per visit.")
      if (!entry.uncompressedSize) throw new ArchiveInputError("One of the NIfTI files in the ZIP is empty.")
      if (entry.uncompressedSize > maxFileBytes) throw new ArchiveInputError("Each extracted NIfTI file must be 350 MB or smaller.")
      expectedBytes += entry.uncompressedSize
      if (expectedBytes > maxTotalBytes) throw new ArchiveInputError("The extracted NIfTI files must be 1 GB or smaller in total.")
    }
    if (!candidates.length || candidates.length % 4 !== 0) throw new ArchiveInputError(`Found ${candidates.length} NIfTI files. Each visit needs exactly four: T1, T1c, T2 and FLAIR. DICOM ZIP is not supported.`)

    const files: File[] = []
    let totalBytes = 0
    onProgress({ phase: "extracting", completed: 0, total: candidates.length, percent: 0 })
    for (const entry of candidates) {
      signal.throwIfAborted()
      const chunks: BlobPart[] = []
      let fileBytes = 0
      // Enforce actual output limits too, not just the ZIP's declared sizes.
      const writer = new WritableStream<Uint8Array>({
        write(chunk) {
          signal.throwIfAborted()
          fileBytes += chunk.byteLength
          totalBytes += chunk.byteLength
          if (fileBytes > maxFileBytes || fileBytes > entry.uncompressedSize || totalBytes > maxTotalBytes) {
            throw new ArchiveInputError("The ZIP expands beyond its declared size or upload limits.")
          }
          chunks.push(new Uint8Array(chunk))
          onProgress({ phase: "extracting", completed: files.length, total: candidates.length, percent: Math.min(99, Math.floor(totalBytes / expectedBytes * 100)) })
        },
      })
      await entry.getData(writer, { signal, checkSignature: true })
      signal.throwIfAborted()
      if (fileBytes !== entry.uncompressedSize) throw new ArchiveInputError("The ZIP is incomplete. Download it again and retry.")
      const path = entry.filename.replaceAll("\\", "/")
      const file = new File(chunks, path.split("/").at(-1)!, { type: "application/octet-stream" })
      Object.defineProperty(file, "webkitRelativePath", { value: path })
      files.push(file)
      onProgress({ phase: "extracting", completed: files.length, total: candidates.length, percent: Math.min(99, Math.floor(totalBytes / expectedBytes * 100)) })
    }
    onProgress({ phase: "ready", completed: files.length, total: files.length, percent: 100 })
    return files
  } catch (error) {
    signal.throwIfAborted()
    if (error instanceof ArchiveInputError) throw error
    throw new ArchiveInputError("The ZIP could not be read. It may be damaged or unsupported. Download it again, or select the extracted NIfTI files.")
  } finally {
    await reader.close()
  }
}
