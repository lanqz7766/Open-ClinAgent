import { useEffect, useMemo, useState } from "react"
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom"
import {
  Activity,
  AlertTriangle,
  Brain,
  ChevronDown,
  Database,
  FileSearch,
  Home,
  ListOrdered,
  LogIn,
  LogOut,
  Menu,
  Moon,
  SearchCheck,
  ShieldCheck,
  Sun,
  TrendingUp,
  UserRound,
  Workflow,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { useIngestFlow } from "@/hooks/useIngestFlow"
import { useChatStream } from "@/hooks/useChatStream"
import { useAuth } from "@/lib/auth"
import type { DemoLayoutContext } from "@/lib/ingestTypes"
import { stripSurfacePrefix, withSurfacePath } from "@/lib/surfaces"
import { cn } from "@/lib/utils"

type SectionKey = "analysis" | "workflows"

type SidebarItem = {
  to: string
  label: string
  icon: React.ComponentType<{ className?: string }>
}

type SidebarSection = SidebarItem & {
  key: SectionKey
  children: SidebarItem[]
}

const stackedLogoSrc = `${import.meta.env.BASE_URL}clinagent-logo-stacked.svg`

const topLevelItems: SidebarItem[] = [
  { to: "/", label: "Home", icon: Home },
  { to: "/account", label: "Account audit", icon: ShieldCheck },
]

const sections: SidebarSection[] = [
  {
    key: "analysis",
    to: "/analysis",
    label: "Analysis",
    icon: TrendingUp,
    children: [
      { to: "/analysis/neuro-report", label: "Neuro MRI", icon: TrendingUp },
      { to: "/analysis/brain-tumor", label: "Brain Tumor", icon: Brain },
      { to: "/analysis/neuro-knowledge", label: "Knowledge", icon: Database },
      { to: "/analysis/radonc-plan", label: "RadOnc", icon: Activity },
    ],
  },
  {
    key: "workflows",
    to: "/workflows",
    label: "Workflows",
    icon: Workflow,
    children: [
      { to: "/workflows/findings", label: "Findings", icon: FileSearch },
      { to: "/workflows/queue", label: "Queue triage", icon: ListOrdered },
      { to: "/workflows/diagnosis", label: "Missed diagnosis", icon: SearchCheck },
      { to: "/workflows/screening", label: "Screening gap", icon: ShieldCheck },
      { to: "/workflows/safety", label: "Radiation safety", icon: AlertTriangle },
    ],
  },
]

const storageKey = "clinagent-demo-theme"

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

function getInitialExpansion(pathname: string) {
  const localPath = stripSurfacePrefix(pathname)
  return {
    workflows: localPath.startsWith("/workflows"),
    analysis: localPath.startsWith("/analysis"),
  }
}

export function DemoLayout() {
  const location = useLocation()
  const navigate = useNavigate()
  const localPath = stripSurfacePrefix(location.pathname)
  const auth = useAuth()
  const chat = useChatStream({ snapshotKey: "demo" })
  const ingest = useIngestFlow()
  const [theme, setTheme] = useState<"light" | "dark">(getInitialTheme)
  const [expanded, setExpanded] = useState<Record<SectionKey, boolean>>(() =>
    getInitialExpansion(location.pathname),
  )
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle("dark", theme === "dark")
    window.localStorage.setItem(storageKey, theme)
  }, [theme])

  useEffect(() => {
    setExpanded((current) => ({
      workflows: current.workflows || localPath.startsWith("/workflows"),
      analysis: current.analysis || localPath.startsWith("/analysis"),
    }))
  }, [localPath])

  const activeLabel = useMemo(() => {
    if (localPath.startsWith("/dashboard")) {
      return "Dashboard"
    }
    const flatItems = [...topLevelItems, ...sections, ...sections.flatMap((section) => section.children)]
    const match = flatItems.find((item) =>
      item.to === "/" ? localPath === "/" : localPath.startsWith(item.to),
    )
    return match?.label ?? "ClinAgent"
  }, [localPath])

  const visibleTopLevelItems = auth.user
    ? topLevelItems
    : topLevelItems.filter((item) => item.to !== "/account")

  const navClasses = ({ isActive }: { isActive: boolean }) =>
    cn(
      "group relative flex min-h-9 min-w-0 items-center gap-3 rounded-2xl border px-3 py-1.5 text-[13px] font-medium transition-all duration-200",
      isActive
        ? "border-sidebar-border/75 bg-[hsl(var(--sidebar-primary)/0.14)] text-sidebar-foreground shadow-[0_10px_24px_-22px_hsl(var(--sidebar-primary)/0.45)]"
        : "border-transparent text-sidebar-foreground/72 hover:border-sidebar-border/70 hover:bg-sidebar-accent hover:text-sidebar-foreground",
    )

  const childNavClasses = ({ isActive }: { isActive: boolean }) =>
    cn(
      "group relative flex min-h-9 min-w-0 items-center gap-3 rounded-xl border px-3 py-2 text-[12px] font-medium transition-all duration-200",
      isActive
        ? "border-sidebar-border/70 bg-[hsl(var(--sidebar-foreground)/0.07)] text-sidebar-foreground"
        : "border-transparent text-sidebar-foreground/62 hover:border-sidebar-border/60 hover:bg-[hsl(var(--sidebar-foreground)/0.045)] hover:text-sidebar-foreground",
    )

  const renderSidebar = () => (
    <div className="flex h-full flex-col overflow-hidden rounded-[1.75rem] border border-sidebar-border/80 bg-sidebar text-sidebar-foreground shadow-[0_30px_80px_-42px_rgba(15,23,42,0.5)]">
      <div className="border-b border-sidebar-border/80 px-4 py-4">
        <div className="rounded-[1.2rem] bg-[hsl(var(--sidebar-foreground)/0.038)] p-3">
          <Link
            aria-label="Open home"
            className="flex min-h-[122px] items-start justify-start rounded-[1rem] px-3 py-3 transition-transform duration-150 ease-out hover:scale-[1.01] active:scale-[0.985]"
            to={withSurfacePath("demo", "/")}
          >
            <img
              alt="ClinAgent stacked logo"
              className="w-[176px] max-w-full object-contain"
              src={stackedLogoSrc}
            />
          </Link>
        </div>
      </div>

      <nav className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        <div className="space-y-1.5">
          <p className="px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/45">Core</p>
          {visibleTopLevelItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                className={navClasses}
                end={item.to === "/"}
                onClick={() => setMobileNavOpen(false)}
                to={withSurfacePath("demo", item.to)}
              >
                <Icon className="size-4" />
                <span className="min-w-0 truncate">{item.label}</span>
              </NavLink>
            )
          })}
        </div>

        {sections.map((section) => {
          const Icon = section.icon
          const open = expanded[section.key]
          return (
            <div className="space-y-1.5" key={section.key}>
              <div className="flex items-center gap-2 px-1">
                <p className="flex-1 px-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-sidebar-foreground/45">
                  {section.label}
                </p>
                <button
                  aria-label={`Toggle ${section.label}`}
                  className="inline-flex size-8 items-center justify-center rounded-xl text-sidebar-foreground/55 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
                  onClick={() =>
                    setExpanded((current) => ({
                      ...current,
                      [section.key]: !current[section.key],
                    }))
                  }
                  type="button"
                >
                  <ChevronDown className={cn("size-4 transition-transform", open ? "rotate-0" : "-rotate-90")} />
                </button>
              </div>

              <NavLink
                className={navClasses}
                onClick={() => setMobileNavOpen(false)}
                to={withSurfacePath("demo", section.to)}
              >
                <Icon className="size-4" />
                <span className="min-w-0 truncate">{section.label}</span>
              </NavLink>

              {open ? (
                <div className="space-y-1 pl-3">
                  {section.children.map((child) => {
                    const ChildIcon = child.icon
                    return (
                      <NavLink
                        key={child.to}
                        className={childNavClasses}
                        onClick={() => setMobileNavOpen(false)}
                        to={withSurfacePath("demo", child.to)}
                      >
                        <ChildIcon className="size-3.5" />
                        <span className="min-w-0 truncate">{child.label}</span>
                      </NavLink>
                    )
                  })}
                </div>
              ) : null}
            </div>
          )
        })}
      </nav>

      <div className="border-t border-sidebar-border/80 px-4 py-4">
        <div className="flex flex-col gap-2">
          <div className="mb-1 flex min-w-0 items-center gap-3 rounded-2xl border border-sidebar-border/70 bg-[hsl(var(--sidebar-foreground)/0.04)] px-3 py-3">
            <div className="grid size-8 shrink-0 place-items-center rounded-xl bg-[hsl(var(--sidebar-primary)/0.18)] text-sidebar-primary">
              <UserRound className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-[12px] font-medium text-sidebar-foreground">
                {auth.user?.name || (auth.auth_required ? "Signed out" : "Local preview")}
              </div>
              <div className="truncate text-[11px] text-sidebar-foreground/52">
                {auth.user?.email || (auth.auth_required ? "Account required" : "No account session")}
              </div>
            </div>
          </div>
          <Button
            className="h-10 min-w-0 justify-start rounded-2xl border-sidebar-border/70 bg-[hsl(var(--sidebar-foreground)/0.05)] text-sidebar-foreground hover:bg-sidebar-accent"
            onClick={() => setTheme((current) => (current === "dark" ? "light" : "dark"))}
            variant="outline"
          >
            {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            <span className="min-w-0 truncate">{theme === "dark" ? "Light mode" : "Dark mode"}</span>
          </Button>
          <Button
            className="h-10 min-w-0 justify-start rounded-2xl border-sidebar-border/70 bg-transparent text-sidebar-foreground/72 hover:bg-sidebar-accent hover:text-sidebar-foreground"
            onClick={() => (auth.user ? void auth.logout() : navigate("/auth"))}
            variant="outline"
          >
            {auth.user ? <LogOut className="size-4" /> : <LogIn className="size-4" />}
            <span className="min-w-0 truncate">{auth.user ? "Sign out" : "Sign in"}</span>
          </Button>
        </div>
      </div>
    </div>
  )

  if (auth.preview_scope === "brain_tumor") {
    if (localPath !== "/analysis/brain-tumor" && localPath !== "/account") {
      return <Navigate replace to="/demo/analysis/brain-tumor" />
    }
    return (
      <div className="min-h-screen bg-background text-foreground">
        <header className="flex min-h-14 flex-wrap items-center justify-between gap-3 border-b border-[hsl(var(--border))] px-4 py-2 sm:px-6">
          <Link className="flex items-center gap-3 text-sm font-semibold" to="/demo/analysis/brain-tumor">
            <Brain aria-hidden="true" className="size-5 text-[hsl(var(--primary))]" />
            <span>ClinAgent <span className="font-normal text-[hsl(var(--muted-foreground))]">/ Brain Tumor</span></span>
          </Link>
          <div className="flex items-center gap-3 text-xs text-[hsl(var(--muted-foreground))]">
            <span>Research preview</span>
            <span className="hidden sm:inline">{auth.user?.name}</span>
            <Link className="inline-flex min-h-11 items-center gap-2 rounded-lg px-2 font-medium hover:bg-muted" to="/demo/account">
              <ShieldCheck aria-hidden="true" className="size-4" />{auth.user?.role === "admin" ? "Accounts" : "Account"}
            </Link>
            <Button aria-label="Toggle color theme" onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")} size="icon-sm" title="Toggle color theme" variant="ghost">
              {theme === "dark" ? <Sun className="size-4" /> : <Moon className="size-4" />}
            </Button>
            <Button onClick={() => void auth.logout()} size="sm" variant="ghost"><LogOut className="size-4" />Sign out</Button>
          </div>
        </header>
        <main className="mx-auto max-w-[1600px] px-4 py-4 sm:px-6">
          <Outlet context={{ chat, ingest } satisfies DemoLayoutContext} />
        </main>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background text-foreground">
      <div className="min-h-screen lg:grid lg:grid-cols-[15.4375rem_1fr]">
        <aside className="hidden px-[13px] py-[13px] lg:block">
          <div className="sticky top-[13px] h-[calc(100vh-26px)]">{renderSidebar()}</div>
        </aside>

        <div className="flex min-h-screen min-w-0 flex-col">
          <header className="sticky top-0 z-20 border-b border-[hsl(var(--border)/0.65)] bg-[hsl(var(--background)/0.78)] backdrop-blur-xl">
            <div className="flex h-[53px] items-center justify-between gap-3 px-4 sm:px-6 xl:px-[26px]">
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

            </div>
          </header>

          <main className="min-w-0 flex-1 overflow-x-hidden px-4 py-5 sm:px-6 xl:px-[26px] xl:py-[19px]">
            <div className="mx-auto flex w-full min-w-0 max-w-[1213px] flex-col">
              <Outlet context={{ chat, ingest } satisfies DemoLayoutContext} />
            </div>
          </main>
        </div>
      </div>

      <Sheet onOpenChange={setMobileNavOpen} open={mobileNavOpen}>
        <SheetContent className="w-[min(22rem,calc(100vw-1rem))] border-sidebar-border bg-transparent p-3 text-sidebar-foreground sm:max-w-none" side="left">
          <SheetHeader className="sr-only">
            <SheetTitle>ClinAgent navigation</SheetTitle>
          </SheetHeader>
          <div className="h-full">{renderSidebar()}</div>
        </SheetContent>
      </Sheet>
    </div>
  )
}
