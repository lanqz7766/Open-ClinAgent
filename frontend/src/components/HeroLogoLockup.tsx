import { BrandWordmark } from "@/components/BrandMark"
import { cn } from "@/lib/utils"

const HERO_LOGO_LOCKUP = {
  // Base width for the horizontal lockup. This is the main size control.
  widthClass: "w-[256px] max-w-[66vw] sm:w-[314px]",
  // Keep the original SVG canvas, then nudge the visible logo down into the hero.
  translateYClass: "translate-y-[10px] sm:translate-y-[14px]",
  // Trim vertical whitespace from the original SVG canvas without scaling the logo.
  trimClass: "-my-[22px] sm:-my-[28px]",
  // Keep the hero stack compact after trimming the transparent canvas.
  wrapperOffsetClass: "-mb-[20px] sm:-mb-[24px]",
} as const

export function HeroLogoLockup({ className }: { className?: string }) {
  return (
    <BrandWordmark
      align="center"
      assetClassName={cn(
        "transform-gpu origin-center",
        HERO_LOGO_LOCKUP.widthClass,
        HERO_LOGO_LOCKUP.translateYClass,
        HERO_LOGO_LOCKUP.trimClass,
      )}
      className={cn(HERO_LOGO_LOCKUP.wrapperOffsetClass, className)}
      variant="horizontal"
    />
  )
}
