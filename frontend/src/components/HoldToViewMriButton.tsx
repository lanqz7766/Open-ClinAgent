import { useCallback, useEffect, useRef } from "react"
import { Eye } from "lucide-react"
import { cn } from "@/lib/utils"

export function HoldToViewMriButton({ pressed, disabled, onPressedChange }: {
  pressed: boolean
  disabled: boolean
  onPressedChange: (pressed: boolean) => void
}) {
  const pointer = useRef<number | null>(null)
  const heldKey = useRef<string | null>(null)
  const release = useCallback(() => {
    pointer.current = null
    heldKey.current = null
    onPressedChange(false)
  }, [onPressedChange])

  useEffect(() => {
    const onVisibilityChange = () => { if (document.hidden) release() }
    window.addEventListener("blur", release)
    document.addEventListener("visibilitychange", onVisibilityChange)
    return () => {
      window.removeEventListener("blur", release)
      document.removeEventListener("visibilitychange", onVisibilityChange)
      release()
    }
  }, [release])

  useEffect(() => { if (disabled) release() }, [disabled, release])

  return <button
    type="button"
    aria-label="Hold to view MRI"
    aria-pressed={pressed}
    disabled={disabled}
    title="Hold to hide the mask; release to restore. Space or Enter when focused."
    className={cn(
      "inline-flex min-h-9 shrink-0 touch-none select-none items-center gap-2 rounded-md border px-3 text-[13px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white disabled:cursor-not-allowed disabled:opacity-40",
      pressed ? "border-sky-300 bg-sky-100 text-sky-950" : "border-zinc-600 bg-zinc-900 text-zinc-200 hover:bg-zinc-800",
    )}
    onPointerDown={(event) => {
      if (disabled || event.button !== 0 || !event.isPrimary) return
      event.preventDefault()
      event.currentTarget.focus()
      event.currentTarget.setPointerCapture(event.pointerId)
      pointer.current = event.pointerId
      onPressedChange(true)
    }}
    onPointerUp={(event) => {
      if (pointer.current !== event.pointerId) return
      pointer.current = null
      onPressedChange(heldKey.current !== null)
    }}
    onPointerCancel={release}
    onLostPointerCapture={() => {
      pointer.current = null
      onPressedChange(heldKey.current !== null)
    }}
    onKeyDown={(event) => {
      if (event.key === "Escape") { release(); return }
      if (disabled || (event.key !== " " && event.key !== "Enter")) return
      event.preventDefault()
      if (event.repeat) return
      heldKey.current = event.key
      onPressedChange(true)
    }}
    onKeyUp={(event) => {
      if (heldKey.current !== event.key) return
      event.preventDefault()
      heldKey.current = null
      onPressedChange(pointer.current !== null)
    }}
    onBlur={release}
    onContextMenu={(event) => event.preventDefault()}
  >
    <Eye aria-hidden="true" className="size-4" />
    Hold to view MRI
  </button>
}
