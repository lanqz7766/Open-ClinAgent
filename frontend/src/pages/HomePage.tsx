import {
  Activity,
  ArrowRight,
  Brain,
} from "lucide-react"
import { Link, useOutletContext } from "react-router-dom"

import { ChatPanel } from "@/components/ChatPanel"
import type { DemoLayoutContext } from "@/lib/ingestTypes"
import { withSurfacePath } from "@/lib/surfaces"

export function HomePage() {
  const { chat, ingest } = useOutletContext<DemoLayoutContext>()

  function handlePrompt(prompt: string) {
    if (prompt === "Open the Neuro MRI Report Generator and show me a brain MRI study.") {
      void chat.sendMessage(prompt)
      return
    }
    chat.setInput(prompt)
  }

  return (
    <div className="space-y-[34px]">
      <div className="mx-auto w-full max-w-[962px]">
        <ChatPanel controller={chat} hero heroFlat ingestController={ingest} />
      </div>
      <section className="grid gap-[13px] xl:grid-cols-3">
        <article className="min-w-0 overflow-hidden rounded-[20.8px] border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--card))] shadow-[0_24px_60px_-40px_rgba(15,23,42,0.4)]">
          <div className="space-y-[13px] px-[19px] py-[19px]">
            <div className="inline-flex max-w-full items-center gap-[6px] rounded-full border border-[hsl(var(--border)/0.68)] px-[10px] py-[4px] text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
              <Brain className="h-3.5 w-3.5" />
              Neuro MRI
            </div>
            <div className="space-y-[6px]">
              <h2 className="text-balance text-[22px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
                Structural, response, and report review.
              </h2>
              <p className="max-w-[468px] text-[14px] leading-[1.62] text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
                Study review, longitudinal change, and report generation in one MRI workspace.
              </p>
            </div>

            <div className="flex flex-wrap gap-[6px] text-[12px] text-[hsl(var(--muted-foreground))]">
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">Volumetry</span>
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">Longitudinal review</span>
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">Report critique</span>
            </div>

            <div className="flex flex-wrap gap-[10px]">
              <Link
                className="inline-flex max-w-full items-center justify-center gap-2 rounded-full bg-[hsl(var(--foreground))] px-[13px] py-[7px] text-center text-[13px] font-medium whitespace-normal text-[hsl(var(--background))] transition hover:opacity-90 [overflow-wrap:anywhere]"
                to={withSurfacePath("demo", "/analysis/neuro-report")}
              >
                Open Neuro MRI
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                className="inline-flex max-w-full items-center justify-center gap-2 rounded-full border border-[hsl(var(--border))] px-[14px] py-[7px] text-center text-[13px] font-medium whitespace-normal text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--muted))] [overflow-wrap:anywhere]"
                to={withSurfacePath("demo", "/analysis/neuro-report?from=home")}
              >
                Open patient library
              </Link>
            </div>
          </div>

          <div className="border-t border-[hsl(var(--border)/0.55)] bg-[hsl(var(--background)/0.38)] px-[19px] pb-[12px] pt-[11px]">
            <div className="flex flex-wrap gap-[6px]">
              {[
                {
                  label: "Open MRI study",
                  prompt: "Open the Neuro MRI Report Generator and show me a brain MRI study.",
                },
                {
                  label: "Review lesion burden trend",
                  prompt: "Review this post-radiotherapy brain MRI trend and summarize lesion burden change.",
                },
              ].map((item) => (
                <button
                  className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--card))] px-[14px] py-[7px] text-left text-[12px] whitespace-normal text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--muted))] [overflow-wrap:anywhere]"
                  key={item.prompt}
                  onClick={() => handlePrompt(item.prompt)}
                  type="button"
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </article>

        <article className="min-w-0 overflow-hidden rounded-[20.8px] border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--card))] shadow-[0_24px_60px_-40px_rgba(15,23,42,0.4)]">
          <div className="space-y-[13px] px-[19px] py-[19px]">
            <div className="inline-flex max-w-full items-center gap-[6px] rounded-full border border-[hsl(var(--border)/0.68)] px-[10px] py-[4px] text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
              <Brain className="h-3.5 w-3.5" />
              Brain Tumor
            </div>
            <div className="space-y-[6px]">
              <h2 className="text-balance text-[22px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
                Glioma volumes and QC for review.
              </h2>
              <p className="max-w-[468px] text-[14px] leading-[1.62] text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
                Confirm MRI sequences, run tumor segmentation, and copy report-ready measurements.
              </p>
            </div>

            <div className="flex flex-wrap gap-[6px] text-[12px] text-[hsl(var(--muted-foreground))]">
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">PACS intake</span>
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">WT / TC / ET</span>
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">QC warnings</span>
            </div>

            <div className="flex flex-wrap gap-[10px]">
              <Link
                className="inline-flex max-w-full items-center justify-center gap-2 rounded-full bg-[hsl(var(--foreground))] px-[13px] py-[7px] text-center text-[13px] font-medium whitespace-normal text-[hsl(var(--background))] transition hover:opacity-90 [overflow-wrap:anywhere]"
                to={withSurfacePath("demo", "/analysis/brain-tumor")}
              >
                Open Brain Tumor
                <ArrowRight className="h-4 w-4" />
              </Link>
            </div>
          </div>

          <div className="border-t border-[hsl(var(--border)/0.55)] bg-[hsl(var(--background)/0.38)] px-[19px] pb-[12px] pt-[11px]">
            <div className="flex flex-wrap gap-[6px]">
              <button
                className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--card))] px-[14px] py-[7px] text-left text-[12px] whitespace-normal text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--muted))] [overflow-wrap:anywhere]"
                onClick={() => chat.setInput("Open the Brain Tumor workspace for a glioma MRI segmentation review.")}
                type="button"
              >
                Start tumor review
              </button>
            </div>
          </div>
        </article>

        <article className="min-w-0 overflow-hidden rounded-[20.8px] border border-[hsl(var(--border)/0.7)] bg-[hsl(var(--card))] shadow-[0_24px_60px_-40px_rgba(15,23,42,0.4)]">
          <div className="space-y-[13px] px-[19px] py-[19px]">
            <div className="inline-flex max-w-full items-center gap-[6px] rounded-full border border-[hsl(var(--border)/0.68)] px-[10px] py-[4px] text-[11px] uppercase tracking-[0.14em] text-[hsl(var(--muted-foreground))]">
              <Activity className="h-3.5 w-3.5" />
              RadOnc
            </div>
            <div className="space-y-[6px]">
              <h2 className="text-balance text-[22px] font-medium tracking-[-0.04em] text-[hsl(var(--foreground))] [overflow-wrap:anywhere]">
                DVH-first plan optimization.
              </h2>
              <p className="max-w-[468px] text-[14px] leading-[1.62] text-[hsl(var(--muted-foreground))] [overflow-wrap:anywhere]">
                Coverage review, objective tuning, and controlled optimization in one planning workspace.
              </p>
            </div>

            <div className="flex flex-wrap gap-[6px] text-[12px] text-[hsl(var(--muted-foreground))]">
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">DVH review</span>
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">Controlled loop</span>
              <span className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] px-[10px] py-[4px] text-center [overflow-wrap:anywhere]">Trade-off summary</span>
            </div>

            <div className="flex flex-wrap gap-[10px]">
              <Link
                className="inline-flex max-w-full items-center justify-center gap-2 rounded-full bg-[hsl(var(--foreground))] px-[13px] py-[7px] text-center text-[13px] font-medium whitespace-normal text-[hsl(var(--background))] transition hover:opacity-90 [overflow-wrap:anywhere]"
                to={withSurfacePath("demo", "/analysis/radonc-plan")}
              >
                Open RadOnc
                <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                className="inline-flex max-w-full items-center justify-center gap-2 rounded-full border border-[hsl(var(--border))] px-[14px] py-[7px] text-center text-[13px] font-medium whitespace-normal text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--muted))] [overflow-wrap:anywhere]"
                to={withSurfacePath("demo", "/analysis/radonc-plan?patient_id=Patient001&autorun=1&from=home")}
              >
                Open auto-loop
              </Link>
            </div>
          </div>

          <div className="border-t border-[hsl(var(--border)/0.55)] bg-[hsl(var(--background)/0.38)] px-[19px] pb-[12px] pt-[11px]">
            <div className="flex flex-wrap gap-[6px]">
              {[
                {
                  label: "Summarize DVH trade-offs",
                  prompt: "Optimize this APBI breast plan and summarize the DVH trade-offs.",
                },
                {
                  label: "Reduce heart dose",
                  prompt: "Lower the heart dose but keep PTV coverage near protocol target.",
                },
              ].map((item) => (
                <button
                  className="max-w-full rounded-full border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--card))] px-[14px] py-[7px] text-left text-[12px] whitespace-normal text-[hsl(var(--foreground))] transition hover:bg-[hsl(var(--muted))] [overflow-wrap:anywhere]"
                  key={item.prompt}
                  onClick={() => chat.setInput(item.prompt)}
                  type="button"
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>
        </article>
      </section>
    </div>
  )
}
