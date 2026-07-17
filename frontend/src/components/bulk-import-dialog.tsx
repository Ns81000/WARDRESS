import { useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Upload } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import * as apiClient from "@/lib/api"
import { ApiError, type BulkImportResult } from "@/lib/api"

/*
 * Bulk site import (Phase 5, §7): CSV upload (read client-side, posted
 * as text) or sitemap crawl. Results are per-row — some rows succeeding
 * and others failing is the expected, visible outcome.
 */

const MAX_CSV_BYTES = 512 * 1024

function rowBadge(status: "created" | "skipped" | "error") {
  if (status === "created") return <Badge variant="clean">Created</Badge>
  if (status === "skipped") return <Badge variant="secondary">Skipped</Badge>
  return <Badge variant="threat">Error</Badge>
}

export function BulkImportDialog() {
  const queryClient = useQueryClient()
  const fileRef = useRef<HTMLInputElement>(null)

  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<"csv" | "sitemap">("csv")
  const [csvText, setCsvText] = useState("")
  const [fileName, setFileName] = useState<string | null>(null)
  const [sitemapUrl, setSitemapUrl] = useState("")
  const [result, setResult] = useState<BulkImportResult | null>(null)
  const [formError, setFormError] = useState<string | null>(null)

  const importSites = useMutation({
    mutationFn: () =>
      apiClient.bulkImportSites(
        mode === "csv" ? { csv_text: csvText } : { sitemap_url: sitemapUrl }
      ),
    onSuccess: (data) => {
      setResult(data)
      setFormError(null)
      if (data.created > 0) {
        void queryClient.invalidateQueries({ queryKey: ["sites"] })
      }
    },
    onError: (err) =>
      setFormError(err instanceof ApiError ? err.message : "Import failed"),
  })

  const onFile = async (file: File | undefined) => {
    if (!file) return
    if (file.size > MAX_CSV_BYTES) {
      setFormError("CSV is larger than 512 KB — split it into smaller files")
      return
    }
    setCsvText(await file.text())
    setFileName(file.name)
    setFormError(null)
  }

  const reset = (openState: boolean) => {
    setOpen(openState)
    if (!openState) {
      setCsvText("")
      setFileName(null)
      setSitemapUrl("")
      setResult(null)
      setFormError(null)
      if (fileRef.current) fileRef.current.value = ""
    }
  }

  const canSubmit = mode === "csv" ? csvText.trim().length > 0 : sitemapUrl.trim().length > 0

  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Upload />
          Bulk import
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Bulk import sites</DialogTitle>
          <DialogDescription>
            Upload a CSV (one URL per line, optionally{" "}
            <span className="text-code-md text-body">url,name</span>) or crawl a
            sitemap.xml. Each row is validated on its own — failures never
            block the rest.
          </DialogDescription>
        </DialogHeader>

        {result === null ? (
          <div className="flex flex-col gap-5">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setMode("csv")}
                className={`rounded-md border px-3 py-1.5 text-button-sm transition-colors ${
                  mode === "csv"
                    ? "border-white/40 text-ink"
                    : "border-hairline-strong text-charcoal hover:text-ink"
                }`}
              >
                CSV file
              </button>
              <button
                type="button"
                onClick={() => setMode("sitemap")}
                className={`rounded-md border px-3 py-1.5 text-button-sm transition-colors ${
                  mode === "sitemap"
                    ? "border-white/40 text-ink"
                    : "border-hairline-strong text-charcoal hover:text-ink"
                }`}
              >
                Sitemap crawl
              </button>
            </div>

            {mode === "csv" ? (
              <div className="flex flex-col gap-2">
                <Label htmlFor="bulk-csv">CSV file</Label>
                <input
                  id="bulk-csv"
                  ref={fileRef}
                  type="file"
                  accept=".csv,text/csv,text/plain"
                  onChange={(e) => void onFile(e.target.files?.[0])}
                  className="text-body-sm text-charcoal file:mr-3 file:rounded-md file:border file:border-hairline-strong file:bg-transparent file:px-3 file:py-1.5 file:text-button-sm file:text-ink"
                />
                {fileName && (
                  <p className="text-caption text-mute">
                    {fileName} — {csvText.split("\n").filter((l) => l.trim()).length} lines
                  </p>
                )}
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                <Label htmlFor="bulk-sitemap">Sitemap URL</Label>
                <Input
                  id="bulk-sitemap"
                  placeholder="https://example.com/sitemap.xml"
                  value={sitemapUrl}
                  onChange={(e) => setSitemapUrl(e.target.value)}
                />
                <p className="text-caption text-mute">
                  Standard urlset sitemaps and one level of sitemap-index
                  nesting; capped at 500 pages per import.
                </p>
              </div>
            )}

            {formError && (
              <p role="alert" className="text-body-sm text-accent-red">
                {formError}
              </p>
            )}
            <DialogFooter>
              <Button
                disabled={!canSubmit || importSites.isPending}
                onClick={() => importSites.mutate()}
              >
                {importSites.isPending ? "Importing" : "Import"}
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant="clean">{result.created} created</Badge>
              <Badge variant="secondary">{result.skipped} skipped</Badge>
              <Badge variant={result.errors > 0 ? "threat" : "secondary"}>
                {result.errors} {result.errors === 1 ? "error" : "errors"}
              </Badge>
            </div>
            <ul className="max-h-72 divide-y divide-hairline overflow-y-auto rounded-md border border-hairline">
              {result.results.map((r) => (
                <li key={`${r.row}-${r.url}`} className="flex items-start gap-3 px-3 py-2">
                  <span className="mt-0.5 w-8 shrink-0 text-code-md text-mute">{r.row}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-body-sm text-body">{r.name ?? r.url}</p>
                    <p className="truncate text-caption text-mute">{r.url}</p>
                    {r.detail && (
                      <p className="text-caption text-charcoal">{r.detail}</p>
                    )}
                  </div>
                  <div className="shrink-0">{rowBadge(r.status)}</div>
                </li>
              ))}
            </ul>
            <p className="text-caption text-mute">
              Created sites are capturing their baselines now.
            </p>
            <DialogFooter>
              <Button variant="outline" onClick={() => setResult(null)}>
                Import more
              </Button>
              <Button onClick={() => reset(false)}>Done</Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
