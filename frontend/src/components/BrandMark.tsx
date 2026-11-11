import type { ReactNode } from "react"
import { Link } from "react-router-dom"

import { cn } from "@/lib/utils"

const markSrc = `${import.meta.env.BASE_URL}clinagent-logo-mark.svg`
const logoSrc = `${import.meta.env.BASE_URL}clinagent-logo.svg`
const horizontalLogoSrc = `${import.meta.env.BASE_URL}clinagent-logo-horizontal.svg`

function BrandAsset({
  alt,
  className,
  src,
}: {
  alt: string
  className?: string
  src: string
}) {
  return <img alt={alt} className={cn("h-auto w-auto object-contain", className)} src={src} />
}

function BrandWrapper({
  children,
  className,
  to,
}: {
  children: ReactNode
  className?: string
  to?: string
}) {
  const classes = cn(
    "group inline-flex min-w-0 rounded-[1.15rem] transition-[transform,filter] duration-150 ease-out select-none",
    to ? "cursor-pointer hover:scale-[1.01] active:scale-[0.965]" : "",
    className,
  )

  if (to) {
    return (
      <Link aria-label="Open home" className={classes} to={to}>
        {children}
      </Link>
    )
  }

  return <div className={classes}>{children}</div>
}

export function BrandMark({
  className,
  compact = false,
}: {
  className?: string
  compact?: boolean
}) {
  return (
    <div className={cn("inline-flex items-center justify-center", className)}>
      <BrandAsset
        alt="ClinAgent logo mark"
        className={cn(
          "drop-shadow-[0_10px_18px_rgba(207,146,69,0.16)] transition-transform duration-200 ease-out group-hover:-translate-y-0.5 group-hover:scale-[1.04] group-active:translate-y-0.5 group-active:scale-[1.08]",
          compact ? "h-11" : "h-18",
        )}
        src={markSrc}
      />
    </div>
  )
}

export function BrandWordmark({
  assetClassName,
  className,
  compact = false,
  surface,
  to,
  align = "start",
  variant = "default",
}: {
  assetClassName?: string
  className?: string
  compact?: boolean
  surface?: string
  to?: string
  align?: "start" | "center"
  variant?: "default" | "horizontal"
}) {
  const centered = align === "center"
  const src = variant === "horizontal" ? horizontalLogoSrc : logoSrc

  return (
    <BrandWrapper className={className} to={to}>
      <div className={cn("inline-flex min-w-0 flex-col gap-2", centered ? "items-center" : "items-start")}>
        <BrandAsset
          alt="ClinAgent logo"
          className={cn(
            "drop-shadow-[0_10px_18px_rgba(207,146,69,0.14)] transition-transform duration-200 ease-out group-hover:-translate-y-0.5 group-hover:scale-[1.02] group-active:translate-y-0.5 group-active:scale-[1.04]",
            variant === "horizontal"
              ? compact
                ? "w-[176px]"
                : "w-[300px] max-w-[72vw] sm:w-[360px]"
              : compact
                ? "w-[140px]"
                : "w-[250px]",
            assetClassName,
          )}
          src={src}
        />
        {surface ? (
          <div className={cn("text-sidebar-foreground/62", compact ? "text-[11px] leading-none" : "text-[12px]")}>
            {surface}
          </div>
        ) : null}
      </div>
    </BrandWrapper>
  )
}
