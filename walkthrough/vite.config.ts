import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Served from GitHub Pages under the project subpath, nested beside the
// static landing page: https://ns81000.github.io/WARDRESS/walkthrough/
// The trailing slash matters — every emitted asset URL is prefixed with it.
export default defineConfig({
  base: '/WARDRESS/walkthrough/',
  plugins: [react(), tailwindcss()],
})
