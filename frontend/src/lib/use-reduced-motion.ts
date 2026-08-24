import { useEffect, useState } from "react"

/*
 * True when the OS asks for reduced motion (prefers-reduced-motion: reduce).
 * A global CSS media query stops stylesheet-driven animation app-wide; this
 * hook exists for the one class CSS cannot reach — SVG SMIL <animate>
 * elements — so ambient topology motion can be switched off at the element
 * level instead of running forever regardless of the user's preference.
 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(
    () =>
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  )

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)")
    const onChange = () => setReduced(mq.matches)
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [])

  return reduced
}
