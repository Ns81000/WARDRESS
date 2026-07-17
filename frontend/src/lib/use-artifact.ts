import { useEffect, useState } from "react"

import { fetchArtifactObjectURL, fetchArtifactText } from "@/lib/api"

/**
 * Fetch an auth-protected artifact (screenshot / HTML snapshot) as an
 * object URL. Plain <img src> can't send the Authorization header, so
 * artifacts are fetched as blobs; the hook owns URL revocation.
 */
export function useArtifact(path: string | null) {
  const [url, setUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!!path)

  useEffect(() => {
    if (!path) {
      setUrl(null)
      setLoading(false)
      return
    }
    let cancelled = false
    let objectUrl: string | null = null
    setLoading(true)
    setError(null)
    fetchArtifactObjectURL(path)
      .then((u) => {
        if (cancelled) {
          URL.revokeObjectURL(u)
          return
        }
        objectUrl = u
        setUrl(u)
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Artifact unavailable")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [path])

  return { url, error, loading }
}

/** Fetch an auth-protected text artifact (HTML snapshot) as a string. */
export function useTextArtifact(path: string | null) {
  const [text, setText] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(!!path)

  useEffect(() => {
    if (!path) {
      setText(null)
      setLoading(false)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchArtifactText(path)
      .then((body) => {
        if (!cancelled) setText(body)
      })
      .catch((err: unknown) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Artifact unavailable")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [path])

  return { text, error, loading }
}
