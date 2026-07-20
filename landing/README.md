# Wardress — Landing Page

A static, desktop-first marketing site for Wardress. Pure HTML/CSS/JS with
GSAP + ScrollTrigger + Lenis (loaded from CDN). No build step.

## Structure

```
landing/
├── index.html          # single-page site
├── styles.css          # Wardress design system (true-black, hairlines, glows)
├── app.js              # GSAP scroll choreography, gauge, copy buttons
├── vercel.json         # static hosting config + cache/security headers
└── assets/
    ├── favicon.svg         # Wardress ward mark
    ├── wardress-logo.svg
    └── brands/             # service logos (theSVG) — Python, React, Docker, …
```

## Local preview

Any static server works. For example:

```bash
npx serve landing
# or
python -m http.server -d landing 5173
```

Then open the printed URL.

## Deploy to Vercel

The site is fully static, so no framework preset is needed.

- **Dashboard:** import the repo, set the **Root Directory** to `landing`,
  framework preset **Other**, no build command, output directory `.`.
- **CLI:**
  ```bash
  cd landing
  vercel --prod
  ```

## Notes

- Desktop-first by design. Screens ≤ 900px get a non-dismissable "open on a
  wider display" overlay.
- All motion respects `prefers-reduced-motion`; with it enabled, every section
  renders fully and statically.
- Design tokens mirror `frontend/src/index.css` so the site stays on-theme.
