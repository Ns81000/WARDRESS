import { useRef, useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Upload } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
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
  const [isDragging, setIsDragging] = useState(false)

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) {
      await onFile(file)
    }
  }

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
      <DialogContent className="max-h-[85vh] overflow-y-auto overflow-x-hidden sm:max-w-2xl">
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
            <div className="relative flex rounded-lg bg-surface-deep p-1 border border-hairline-strong max-w-[240px]">
              <div
                className="absolute top-1 bottom-1 rounded-md bg-surface-elevated transition-all duration-200 ease-out border border-hairline-strong"
                style={{
                  left: mode === "csv" ? "4px" : "120px",
                  width: "116px",
                }}
              />
              <button
                type="button"
                onClick={() => setMode("csv")}
                className={cn(
                  "relative z-10 w-[116px] py-1.5 text-center text-button-sm transition-colors duration-200 cursor-pointer",
                  mode === "csv" ? "text-ink" : "text-charcoal hover:text-ink"
                )}
              >
                CSV file
              </button>
              <button
                type="button"
                onClick={() => setMode("sitemap")}
                className={cn(
                  "relative z-10 w-[116px] py-1.5 text-center text-button-sm transition-colors duration-200 cursor-pointer",
                  mode === "sitemap" ? "text-ink" : "text-charcoal hover:text-ink"
                )}
              >
                Sitemap
              </button>
            </div>

            {mode === "csv" ? (
              <div className="flex flex-col gap-2">
                <Label>CSV file</Label>
                <div
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => fileRef.current?.click()}
                  className={cn(
                    "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed p-8 text-center cursor-pointer transition-all duration-200 bg-surface-deep",
                    isDragging
                      ? "border-accent-blue bg-glow-blue/10"
                      : "border-hairline-strong hover:border-white/20 hover:bg-surface-card"
                  )}
                >
                  <input
                    ref={fileRef}
                    type="file"
                    accept=".csv,text/csv,text/plain"
                    className="hidden"
                    onChange={(e) => void onFile(e.target.files?.[0])}
                  />
                  <Upload className={cn("size-6 transition-colors duration-200", isDragging ? "text-accent-blue" : "text-charcoal")} />
                  <div>
                    <p className="text-body-sm text-body">
                      {fileName ? (
                        <span className="text-accent-green font-medium">{fileName}</span>
                      ) : (
                        <span>Click to upload or drag & drop</span>
                      )}
                    </p>
                    <p className="mt-1 text-caption text-mute">
                      {fileName
                        ? `${csvText.split("\n").filter((l) => l.trim()).length} rows detected`
                        : "CSV up to 512 KB"}
                    </p>
                  </div>
                </div>
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
            <ul className="max-h-72 divide-y divide-hairline overflow-y-auto overflow-x-hidden rounded-md border border-hairline">
              {result.results.map((r) => (
                <li key={`${r.row}-${r.url}`} className="flex items-start gap-3 px-3 py-2">
                  <span className="mt-0.5 w-8 shrink-0 text-code-md text-mute">{r.row}</span>
                  <div className="min-w-0 flex-1 break-words">
                    <p className="text-body-sm text-body font-medium whitespace-normal">{r.name ?? r.url}</p>
                    <p className="text-caption text-mute whitespace-normal break-all mt-0.5">{r.url}</p>
                    {r.detail && (
                      <p className="text-caption text-charcoal whitespace-normal break-words mt-1">{r.detail}</p>
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
