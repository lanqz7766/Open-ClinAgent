import { useEffect, useMemo, useState, type FormEvent } from "react"
import { Database, Search } from "lucide-react"
import { useNavigate } from "react-router-dom"

import { SummaryMetric } from "@/components/SummaryMetric"
import { WorkspacePanel } from "@/components/WorkspacePanel"
import { Button } from "@/components/ui/button"
import { useApi } from "@/hooks/useApi"
import type {
  NeuroKnowledgeAsset,
  NeuroKnowledgeAssetsResponse,
  NeuroKnowledgeCase,
  NeuroKnowledgeCohortEntry,
  NeuroKnowledgeCohortResponse,
  NeuroKnowledgeHealth,
  NeuroKnowledgeSearchResponse,
  NeuroKnowledgeStudy,
} from "@/types/api"

async function fetchJson<T>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }
  return (await response.json()) as T
}

function boolLabel(value: boolean | number | undefined) {
  return value ? "Yes" : "No"
}

function formatDate(value?: string) {
  if (!value) {
    return "—"
  }
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleDateString()
}

function assetTone(asset: NeuroKnowledgeAsset) {
  if (asset.asset_kind === "mri_zip") {
    return "MRI"
  }
  if (asset.asset_kind === "vista_zip") {
    return "Vista"
  }
  if (asset.asset_kind === "nvseg_zip") {
    return "NVSeg"
  }
  return asset.asset_kind
}

export function NeuroKnowledgePage() {
  const navigate = useNavigate()
  const health = useApi<NeuroKnowledgeHealth>("/api/neuro-knowledge/health")
  const cohort = useApi<NeuroKnowledgeCohortResponse>("/api/neuro-knowledge/cohorts/v1")
  const [selectedPatientUid, setSelectedPatientUid] = useState("")
  const [requestedStudyUid, setRequestedStudyUid] = useState<string | null>(null)
  const [selectedStudyUid, setSelectedStudyUid] = useState("")
  const [casePayload, setCasePayload] = useState<NeuroKnowledgeCase | null>(null)
  const [assetsPayload, setAssetsPayload] = useState<NeuroKnowledgeAssetsResponse | null>(null)
  const [studyPayload, setStudyPayload] = useState<NeuroKnowledgeStudy | null>(null)
  const [searchQuery, setSearchQuery] = useState("")
  const [searchResults, setSearchResults] = useState<NeuroKnowledgeSearchResponse | null>(null)
  const [caseLoading, setCaseLoading] = useState(false)
  const [studyLoading, setStudyLoading] = useState(false)
  const [searchLoading, setSearchLoading] = useState(false)
  const [caseError, setCaseError] = useState<string | null>(null)
  const [studyError, setStudyError] = useState<string | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)

  useEffect(() => {
    const firstPatient = cohort.data?.cohort?.[0]?.patient_uid
    if (firstPatient && !selectedPatientUid) {
      setSelectedPatientUid(firstPatient)
    }
  }, [cohort.data, selectedPatientUid])

  useEffect(() => {
    if (!selectedPatientUid) {
      return
    }

    let cancelled = false
    setCaseLoading(true)
    setCaseError(null)

    Promise.all([
      fetchJson<NeuroKnowledgeCase>(`/api/neuro-knowledge/cases/${selectedPatientUid}`),
      fetchJson<NeuroKnowledgeAssetsResponse>(`/api/neuro-knowledge/cases/${selectedPatientUid}/assets`),
    ])
      .then(([caseData, assetsData]) => {
        if (cancelled) {
          return
        }
        setCasePayload(caseData)
        setAssetsPayload(assetsData)
        const availableStudies = caseData.studies ?? []
        const requestedStudy = requestedStudyUid
          ? availableStudies.find((study) => study.study_uid === requestedStudyUid)
          : null
        const nextStudyUid = requestedStudy?.study_uid ?? availableStudies[0]?.study_uid ?? ""
        setSelectedStudyUid(nextStudyUid)
        setRequestedStudyUid(null)
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCaseError(error instanceof Error ? error.message : "Failed to load case")
          setCasePayload(null)
          setAssetsPayload(null)
          setSelectedStudyUid("")
        }
      })
      .finally(() => {
        if (!cancelled) {
          setCaseLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [requestedStudyUid, selectedPatientUid])

  useEffect(() => {
    if (!selectedStudyUid) {
      setStudyPayload(null)
      return
    }

    let cancelled = false
    setStudyLoading(true)
    setStudyError(null)

    fetchJson<NeuroKnowledgeStudy>(`/api/neuro-knowledge/studies/${selectedStudyUid}`)
      .then((payload) => {
        if (!cancelled) {
          setStudyPayload(payload)
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setStudyError(error instanceof Error ? error.message : "Failed to load study")
          setStudyPayload(null)
        }
      })
      .finally(() => {
        if (!cancelled) {
          setStudyLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [selectedStudyUid])

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = searchQuery.trim()
    if (!query) {
      setSearchResults(null)
      setSearchError(null)
      return
    }

    setSearchLoading(true)
    setSearchError(null)
    try {
      const payload = await fetchJson<NeuroKnowledgeSearchResponse>(
        `/api/neuro-knowledge/search?q=${encodeURIComponent(query)}`,
      )
      setSearchResults(payload)
    } catch (error) {
      setSearchError(error instanceof Error ? error.message : "Search failed")
      setSearchResults(null)
    } finally {
      setSearchLoading(false)
    }
  }

  function handleSelectCase(entry: NeuroKnowledgeCohortEntry) {
    setSelectedPatientUid(entry.patient_uid)
    setRequestedStudyUid(null)
    setSearchError(null)
  }

  function handleSelectSearchResult(result: { patient_uid: string; study_uid?: string }) {
    setSelectedPatientUid(result.patient_uid)
    setRequestedStudyUid(result.study_uid ?? null)
  }

  const selectedSummary = casePayload?.summary
  const selectedAssets = assetsPayload?.assets ?? []
  const studyRows = casePayload?.studies ?? []
  const currentCohortEntry = useMemo(
    () => cohort.data?.cohort?.find((entry) => entry.patient_uid === selectedPatientUid) ?? null,
    [cohort.data, selectedPatientUid],
  )
  const canOpenInAnalysis = Boolean(selectedPatientUid && selectedStudyUid)

  function handleOpenInNeuroAnalysis() {
    if (!selectedPatientUid || !selectedStudyUid) {
      return
    }
    const params = new URLSearchParams({
      source: "knowledge",
      knowledge_patient_uid: selectedPatientUid,
      knowledge_study_uid: selectedStudyUid,
      from: "knowledge",
    })
    navigate(`/demo/analysis/neuro-report?${params.toString()}`)
  }

  return (
    <div className="space-y-6">
      <WorkspacePanel
        title="MR-RATE Knowledge Explorer"
      subtitle="Read-only research knowledge surface proxied through the ClinAgent gateway. This page never connects directly to private compute hosts."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <SummaryMetric
            label="Service"
            value={health.loading ? "Checking" : health.data?.ok ? "Online" : "Offline"}
            delta={health.error ?? "Gateway proxy to MR-RATE"}
            tone={health.data?.ok ? "positive" : "warning"}
          />
          <SummaryMetric
            label="Cases"
            value={String(health.data?.counts?.cases ?? cohort.data?.cohort?.length ?? "—")}
            delta="Indexed cohort and catalog"
          />
          <SummaryMetric
            label="Studies"
            value={String(health.data?.counts?.studies ?? "—")}
            delta="Study-level report entries"
          />
          <SummaryMetric
            label="Assets"
            value={String(health.data?.counts?.assets ?? "—")}
            delta="MRI and segmentation path references"
          />
        </div>
        <div className="mt-4 flex justify-end">
          <Button disabled={!canOpenInAnalysis} onClick={handleOpenInNeuroAnalysis} type="button">
            Open in Neuro Analysis
          </Button>
        </div>
      </WorkspacePanel>

      <div className="grid gap-6 xl:grid-cols-[280px_minmax(0,1fr)]">
        <WorkspacePanel
          title="Cohort"
          subtitle={cohort.error ?? `${cohort.data?.cohort?.length ?? 0} candidate cases available`}
        >
          <div className="space-y-2">
            {(cohort.data?.cohort ?? []).map((entry) => (
              <button
                className={`w-full rounded-xl border px-3 py-3 text-left transition-colors ${
                  entry.patient_uid === selectedPatientUid
                    ? "border-[hsl(var(--foreground)/0.16)] bg-[hsl(var(--accent))]"
                    : "border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent)/0.7)]"
                }`}
                key={entry.patient_uid}
                onClick={() => handleSelectCase(entry)}
                type="button"
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">Case {entry.patient_uid}</span>
                  <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
                    #{entry.cohort_rank ?? "—"}
                  </span>
                </div>
                <p className="mt-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                  {entry.summary_text || entry.selection_reason || "No summary available."}
                </p>
                <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-[hsl(var(--muted-foreground))]">
                  <span>{entry.study_count} studies</span>
                  <span>{entry.report_count} reports</span>
                  <span>{entry.case_label ?? "uncategorized"}</span>
                </div>
              </button>
            ))}
            {!cohort.loading && !cohort.data?.cohort?.length ? (
              <p className="text-sm text-[hsl(var(--muted-foreground))]">No cohort entries available.</p>
            ) : null}
          </div>
        </WorkspacePanel>

        <div className="space-y-6">
          <WorkspacePanel
            title={selectedPatientUid ? `Case ${selectedPatientUid}` : "Knowledge search"}
            subtitle={caseError ?? selectedSummary?.summary_text ?? "Search cases, review assets, and inspect study-level report text."}
          >
            <form className="mb-5 flex flex-col gap-3 md:flex-row" onSubmit={handleSearch}>
              <label className="flex-1">
                <span className="sr-only">Search MR-RATE knowledge</span>
                <div className="flex items-center gap-2 rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] px-3">
                  <Search className="size-4 text-[hsl(var(--muted-foreground))]" />
                  <input
                    className="h-11 w-full bg-transparent text-sm outline-none"
                    onChange={(event) => setSearchQuery(event.target.value)}
                    placeholder="Search findings, impression, or case summary"
                    value={searchQuery}
                  />
                </div>
              </label>
              <Button disabled={searchLoading} type="submit">
                {searchLoading ? "Searching..." : "Search"}
              </Button>
            </form>

            {searchError ? (
              <div className="mb-4 rounded-xl border border-[hsl(var(--destructive)/0.3)] bg-[hsl(var(--destructive)/0.08)] px-4 py-3 text-sm text-[hsl(var(--destructive))]">
                {searchError}
              </div>
            ) : null}

            {searchResults?.results?.length ? (
              <div className="mb-6 rounded-2xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-4">
                <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                  <Database className="size-4" />
                  Search results
                </div>
                <div className="space-y-2">
                  {searchResults.results.map((result, index) => (
                    <button
                      className="w-full rounded-xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--card))] px-3 py-3 text-left hover:bg-[hsl(var(--accent))]"
                      key={`${result.patient_uid}-${result.study_uid ?? index}`}
                      onClick={() => handleSelectSearchResult(result)}
                      type="button"
                    >
                      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
                        <span>Case {result.patient_uid}</span>
                        {result.study_uid ? <span className="text-[hsl(var(--muted-foreground))]">Study {result.study_uid}</span> : null}
                      </div>
                      <p className="mt-2 text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                        {result.snippet || result.summary_text || result.findings || result.impression || "Matched result"}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <SummaryMetric label="Studies" value={String(selectedSummary?.study_count ?? "—")} />
              <SummaryMetric label="Reports" value={String(selectedSummary?.report_count ?? "—")} />
              <SummaryMetric
                label="MRI zip"
                value={boolLabel(casePayload?.case?.has_mri_zip)}
                delta={currentCohortEntry?.cohort_shape ?? "Path indexed"}
              />
              <SummaryMetric
                label="Segmentation"
                value={`${boolLabel(casePayload?.case?.has_vista_seg)}/${boolLabel(casePayload?.case?.has_nvseg)}`}
                delta="Vista / NVSeg"
              />
            </div>
          </WorkspacePanel>

          <div className="grid gap-6 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
            <WorkspacePanel
              title="Studies"
              subtitle={caseLoading ? "Loading selected case..." : "Select a study to inspect report content."}
            >
              {caseError ? (
                <p className="text-sm text-[hsl(var(--destructive))]">{caseError}</p>
              ) : (
                <div className="space-y-3">
                  {(studyRows ?? []).map((study) => (
                    <button
                      className={`w-full rounded-xl border px-3 py-3 text-left ${
                        study.study_uid === selectedStudyUid
                          ? "border-[hsl(var(--foreground)/0.16)] bg-[hsl(var(--accent))]"
                          : "border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent)/0.7)]"
                      }`}
                      key={study.study_uid}
                      onClick={() => setSelectedStudyUid(study.study_uid)}
                      type="button"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-medium">{study.study_uid}</span>
                        <span className="text-[11px] text-[hsl(var(--muted-foreground))]">
                          {formatDate(study.anon_study_date)}
                        </span>
                      </div>
                      <div className="mt-2 text-[12px] text-[hsl(var(--muted-foreground))]">
                        Report: {boolLabel(study.report_available)}
                      </div>
                    </button>
                  ))}
                  {!studyRows.length && !caseLoading ? (
                    <p className="text-sm text-[hsl(var(--muted-foreground))]">No studies indexed for this case.</p>
                  ) : null}
                </div>
              )}
            </WorkspacePanel>

            <WorkspacePanel
              title={selectedStudyUid ? `Study ${selectedStudyUid}` : "Study detail"}
              subtitle={studyError ?? "Report text, summary, and metadata for the selected study."}
            >
              {studyLoading ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))]">Loading study detail...</p>
              ) : studyPayload ? (
                <div className="space-y-4">
                  <div className="grid gap-4 md:grid-cols-2">
                    <SummaryMetric label="Date" value={formatDate(studyPayload.study?.anon_study_date)} />
                    <SummaryMetric
                      label="Report available"
                      value={boolLabel(studyPayload.study?.report_available)}
                    />
                  </div>
                  <div className="space-y-3 rounded-2xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-4">
                    <div>
                      <h3 className="text-sm font-medium">Clinical information</h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-[hsl(var(--muted-foreground))]">
                        {studyPayload.report?.clinical_information || "—"}
                      </p>
                    </div>
                    <div>
                      <h3 className="text-sm font-medium">Findings</h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-[hsl(var(--muted-foreground))]">
                        {studyPayload.report?.findings || "—"}
                      </p>
                    </div>
                    <div>
                      <h3 className="text-sm font-medium">Impression</h3>
                      <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-[hsl(var(--muted-foreground))]">
                        {studyPayload.report?.impression || "—"}
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-[hsl(var(--muted-foreground))]">Select a study to inspect detail.</p>
              )}
            </WorkspacePanel>
          </div>

          <WorkspacePanel
            title="Assets"
            subtitle="Indexed source paths only. The gateway does not copy or download MRI files."
          >
            <div className="space-y-3">
              {selectedAssets.map((asset) => (
                <div
                  className="rounded-2xl border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--background))] p-4"
                  key={`${asset.asset_id}-${asset.source_path}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-medium">{assetTone(asset)}</h3>
                      <p className="mt-1 break-all text-[12px] leading-5 text-[hsl(var(--muted-foreground))]">
                        {asset.source_path}
                      </p>
                    </div>
                    <div className="text-right text-[12px] text-[hsl(var(--muted-foreground))]">
                      <div>{asset.member_count} members</div>
                      <div>{asset.batch_id || "—"}</div>
                    </div>
                  </div>
                  {asset.segmentation_members?.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {asset.segmentation_members.slice(0, 6).map((member) => (
                        <span
                          className="rounded-full bg-[hsl(var(--accent))] px-2.5 py-1 text-[11px] text-[hsl(var(--muted-foreground))]"
                          key={member.member_path}
                        >
                          {member.sequence_token || member.segmentation_family || member.member_path}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              ))}
              {!selectedAssets.length && !caseLoading ? (
                <p className="text-sm text-[hsl(var(--muted-foreground))]">No indexed assets for this case.</p>
              ) : null}
            </div>
          </WorkspacePanel>
        </div>
      </div>
    </div>
  )
}
