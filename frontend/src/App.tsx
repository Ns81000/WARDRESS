/**
 * Wardress — Phase 0 placeholder shell.
 * The real dashboard shell (nav bar, logo, routed pages) arrives in Phase 1;
 * this exists only to prove the toolchain (React 19 + Vite + Tailwind v4)
 * builds and renders on the true-black canvas.
 */
export default function App() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas">
      <div className="rounded-lg border border-hairline-strong bg-surface-card px-8 py-6 text-center">
        <h1 className="text-2xl font-medium tracking-tight text-ink">Wardress</h1>
        <p className="mt-2 text-sm text-charcoal">
          Defacement detection platform — Phase 0 stack online.
        </p>
      </div>
    </main>
  )
}
