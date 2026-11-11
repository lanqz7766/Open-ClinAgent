import { useCallback, useEffect, useState } from "react"

export function useApi<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(Boolean(url))
  const [error, setError] = useState<string | null>(null)
  const [reloadToken, setReloadToken] = useState(0)

  useEffect(() => {
    let cancelled = false

    if (!url) {
      setLoading(false)
      return
    }

    setLoading(true)
    setError(null)

    fetch(url, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Request failed with status ${response.status}`)
        }

        return (await response.json()) as T
      })
      .then((payload) => {
        if (!cancelled) {
          setData(payload)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Request failed")
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [reloadToken, url])

  const refetch = useCallback(() => {
    setReloadToken((current) => current + 1)
  }, [])

  return { data, loading, error, refetch }
}

export async function postApi<T>(url: string, body: object): Promise<T> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify(body),
  })

  return res.json() as Promise<T>
}
