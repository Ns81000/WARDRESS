/*
 * The Wardress ward mark as an inline React component (single even-odd
 * path, monochrome — source of truth is /assets/brand/wardress-logo.svg).
 */
export function WardressMark({ size = 24 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 512 512"
      role="img"
      aria-label="Wardress"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M256 26 L458 98 L458 282 L256 486 L54 282 L54 98 Z M256 152 a54 54 0 0 0 -26 101.3 L198 366 L314 366 L282 253.3 A54 54 0 0 0 256 152 Z"
      />
    </svg>
  )
}
