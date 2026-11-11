import { useEffect, useMemo, useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { Activity, Menu, Moon, Settings2, Sun } from "lucide-react"

import { BrandWordmark } from "@/components/BrandMark"
import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useChatStream } from "@/hooks/useChatStream"
import type { DevLayoutContext } from "@/lib/ingestTypes"
import { stripSurfacePrefix, withSurfacePath } from "@/lib/surfaces"
import { cn } from "@/lib/utils"

const storageKey = "clinagent-dev-theme"

function getInitialTheme() {
  if (typeof window === "undefined") {
    return "light"
  }
  const saved = window.localStorage.getItem(storageKey)
  if (saved === "light" || saved === "dark") {
    return saved
  }
  return "light"
}

function HealthDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex size-2.5 rounded-full",
        ok ? "bg-[hsl(var(--status-ok))] shadow-[0_0_16px_hsl(var(--status-ok)/0.5)]" : "bg-[hsl(var(--destructive))]",
      )}
    />
  )
}

export function DevLayout() {
  const location = useLocation()
  const localPath = stripSurfacePrefix(location.pathname)
  const [theme, setTheme] = useState<"light" | "dark">(getInitialTheme)
  const [healthOk, setHealthOk] = useState(false)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const chat = useChatStream({ endpoint: "/api/dev/execute-stream", snapshotKey: "dev" })

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle("dark", theme === "dark")
    window.localStorage.setItem(storageKey, theme)
  }, [theme])

  useEffect(() => {
    let cancelled = false
    fetch("/health")
      .then((response) => response.ok)
      .then((ok) => {
        if (!cancelled) {
          setHealthOk(ok)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setHealthOk(false)
        }
      })
    return () => {
      cancelled = true
    }
  }, [])

  const activeLabel = useMemo(() => (localPath === "/" ? "Developer Console" : localPath), [localPath])

  const navClasses = ({ isActive }: { isActive: boolean }) =>
    cn(
      "group relative flex min-h-10 items-center gap-3 rounded-2xl border px-3.5 py-2 text-[13px] font-medium transition-all duration-200",
      isActive
        ? "border-transparent bg-sidebar-primary text-sidebar-primary-foreground shadow-[0_16px_34px_-20px_hsl(var(--sidebar-primary)/0.95)]"
        : "border-transparent text-sidebar-foreground/72 hover:border-sidebar-border/70 hover:bg-sidebar-accent hover:text-sidebar-foreground",
    )

  const renderSidebar = (mobile = false) => (
    <div className="flex h-full flex-col overflow-hidden rounded-[1.75rem] border border-sidebar-border/80 bg-sidebar text-sidebar-foreground shadow-[0_30px_80px_-42px_rgba(15,23,42,0.5)]">
      <div className="border-b border-sidebar-border/80 px-4 py-4">
        <div className="rounded-[1.35rem] bg-[hsl(var(--sidebar-foreground)/0.055)] px-3 py-3">
          <BrandWordmark surface="Dev" to={withSurfacePath("dev", "/")} />
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <div className="rounded-[1.15rem] border border-sidebar-border/70 bg-[hsl(var(--sidebar-foreground)/0.045)] px-3 py-2">
            <div className="text-[10px] uppercase tracking-[0.16em] text-sidebar-foreground/48">Health</div>
            <div className="mt-1 flex items-center gap-2 text-[12px] font-medium text-sidebar-foreground">
              <HealthDot ok={healthOk} />
              <span>{healthOk ? "Ready" : "Offline"}</span>
            </div>
          </div>
          <div className="rounded-[1.15rem] border border-sidebar-border/70 bg-[hsl(var(--sidebar-foreground)/0.045)] px-3 py-2">
            <div className="text-[10px] uppercase tracking-[0.16em] text-sidebar-foreground/48">Theme</div>
            <div className="mt-1 text-[12px] font-medium text-sidebar-foreground">{theme === "dark" ? "Dark" : "Light"}</div>
          </div>
        </div>
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <div className="space-y-1.5">
          <p className="px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/45">Runtime</p>
          <NavLink className={navClasses} end onClick={() => setMobileNavOpen(false)} to={withSurfacePath("dev", "/")}>
            <Activity className="size-4" />
            <span>Runtime Console</span>
          </NavLink>
        </div>

        <div className="space-y-1.5">
          <p className="px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/45">Surface</p>
          <NavLink className={navClasses} onClick={() => setMobileNavOpen(false)} to={withSurfacePath("demo", "/")}>
            <Settings2 className="size-4" />
            <span>Open User Surface</span>
          </NavLink>
        </div>
      </nav>

      <div className="border-t border-sidebar-border/80 px-4 py-4">
        <div className="flex flex-col gap-2">
          <Button
            className="h-10 justify-start rounded-2xl border-sidebar-border/70 bg-[hsl(var(--sidebar-foreground)/0.05)] text-sidebar-foreground hover:bg-sidebar-accent"
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            variant="outline"
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            <span>{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </Button>
          {!mobile ? (
            <div className="flex items-center gap-2 px-1 text-[12px] text-sidebar-foreground/58">
              <HealthDot ok={healthOk} />
              <span>Developer health</span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="min-h-screen lg:grid lg:grid-cols-[19rem_1fr]">
        <aside className="hidden px-4 py-4 lg:block">
          <div className="sticky top-4 h-[calc(100vh-2rem)]">{renderSidebar()}</div>
        </aside>

        <div className="flex min-h-screen min-w-0 flex-col">
          <header className="sticky top-0 z-20 border-b border-[hsl(var(--border)/0.65)] bg-[hsl(var(--background)/0.78)] backdrop-blur-xl">
            <div className="flex h-16 items-center justify-between gap-3 px-4 sm:px-6 xl:px-8">
              <div className="flex min-w-0 items-center gap-3">
                <Button
                  className="lg:hidden"
                  onClick={() => setMobileNavOpen(true)}
                  size="icon-sm"
                  variant="outline"
                >
                  <Menu className="size-4" />
                </Button>
                <div className="min-w-0">
                  <div className="truncate text-[15px] font-semibold tracking-[-0.03em] text-[hsl(var(--foreground))]">
                    {activeLabel}
                  </div>
                </div>
              </div>

              <div className="hidden items-center gap-2 md:flex">
                <div className="rounded-full border border-[hsl(var(--border)/0.65)] bg-[hsl(var(--card)/0.72)] px-3 py-1 text-[11px] text-[hsl(var(--muted-foreground))]">
                  {healthOk ? "Runtime ready" : "Runtime offline"}
                </div>
              </div>
            </div>
          </header>

          <main className="flex-1 px-4 py-5 sm:px-6 xl:px-8 xl:py-6">
            <Outlet context={{ chat } satisfies DevLayoutContext} />
          </main>
        </div>
      </div>

      <Sheet onOpenChange={setMobileNavOpen} open={mobileNavOpen}>
        <SheetContent className="w-[22rem] border-sidebar-border bg-transparent p-3 text-sidebar-foreground sm:max-w-none" side="left">
          <SheetHeader className="sr-only">
            <SheetTitle>Developer navigation</SheetTitle>
          </SheetHeader>
          <div className="h-full">{renderSidebar(true)}</div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
