import { useCallback, useMemo, useState } from "react"

import type { IngestController, IngestProfile, IngestWorkspace } from "@/lib/ingestTypes"

type Envelope<T> = {
  ok: boolean
  data: T
  error: string | null
}

async function parseEnvelope<T>(response: Response): Promise<T> {
  const payload = (await response.json()) as Envelope<T>
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `Request failed with status ${response.status}`)
  }
  return payload.data
}

function chooseDefaultPatient(profile: IngestProfile | null) {
  if (!profile?.patients.length) {
    return null
  }
  return [...profile.patients].sort((a, b) => b.timepoints - a.timepoints)[0]?.patient_uid ?? null
}

export function useIngestFlow(): IngestController {
  const [sourcePath, setSourcePath] = useState("")
  const [profile, setProfile] = useState<IngestProfile | null>(null)
  const [workspace, setWorkspace] = useState<IngestWorkspace | null>(null)
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)
  const [selectedPatientUid, setSelectedPatientUid] = useState<string | null>(null)
  const [status, setStatus] = useState<IngestController["status"]>("idle")
  const [error, setError] = useState<string | null>(null)

  const profileSource = useCallback(async (sourcePathOverride?: string) => {
    const nextSource = (sourcePathOverride ?? sourcePath).trim()
    if (!nextSource) {
      setError("Source path is required.")
      setStatus("error")
      return
    }

    setStatus("profiling")
    setError(null)
    setWorkspace(null)
    setWorkspaceId(null)

    try {
      const data = await parseEnvelope<IngestProfile>(
        await fetch("/api/ingest/profile", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source_path: nextSource }),
        }),
      )
      setSourcePath(nextSource)
      setProfile(data)
      setSelectedPatientUid(chooseDefaultPatient(data))
      setStatus("profiled")
    } catch (nextError) {
      setProfile(null)
      setStatus("error")
      setError(nextError instanceof Error ? nextError.message : "Profiling failed.")
    }
  }, [sourcePath])

  const profileUpload = useCallback(async (file: File) => {
    setStatus("profiling")
    setError(null)
    setWorkspace(null)
    setWorkspaceId(null)

    try {
      const form = new FormData()
      form.append("upload", file)
      const data = await parseEnvelope<IngestProfile>(
        await fetch("/api/ingest/profile", {
          method: "POST",
          body: form,
        }),
      )
      setSourcePath(data.source_path)
      setProfile(data)
      setSelectedPatientUid(chooseDefaultPatient(data))
      setStatus("profiled")
    } catch (nextError) {
      setProfile(null)
      setStatus("error")
      setError(nextError instanceof Error ? nextError.message : "Upload profiling failed.")
    }
  }, [])

  const confirmWorkflow = useCallback(async (workflow: string) => {
    if (!profile) {
      setError("Profile data is required before confirmation.")
      setStatus("error")
      return
    }

    setStatus("confirming")
    setError(null)

    try {
      const confirmData = await parseEnvelope<{ workspace_id: string; status: string }>(
        await fetch("/api/ingest/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            source_path: profile.source_path,
            selected_workflow: workflow,
            patient_overrides: selectedPatientUid ? { patient_uid: selectedPatientUid } : {},
          }),
        }),
      )
      const nextWorkspace = await parseEnvelope<IngestWorkspace>(
        await fetch(`/api/ingest/workspace/${confirmData.workspace_id}`),
      )
      setWorkspaceId(confirmData.workspace_id)
      setWorkspace(nextWorkspace)
      setStatus("ready")
    } catch (nextError) {
      setStatus("error")
      setError(nextError instanceof Error ? nextError.message : "Workspace assembly failed.")
    }
  }, [profile, selectedPatientUid])

  const clear = useCallback(() => {
    setSourcePath("")
    setProfile(null)
    setWorkspace(null)
    setWorkspaceId(null)
    setSelectedPatientUid(null)
    setStatus("idle")
    setError(null)
  }, [])

  return useMemo(
    () => ({
      sourcePath,
      setSourcePath,
      profile,
      workspace,
      workspaceId,
      selectedPatientUid,
      setSelectedPatientUid,
      status,
      error,
      profileSource,
      profileUpload,
      confirmWorkflow,
      clear,
    }),
    [clear, confirmWorkflow, error, profile, profileSource, profileUpload, selectedPatientUid, sourcePath, status, workspace, workspaceId],
  )
}
