import { useEffect, useState } from "react"
let csrf = ""
export function setCsrf(token: string) {
  csrf = token
}
export class APIError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}
export async function api<T>(
  path: string,
  method = "GET",
  data?: unknown
): Promise<T> {
  const headers: Record<string, string> = {}
  if (method !== "GET") headers["X-CSRF-Token"] = csrf
  const body =
    data instanceof FormData
      ? data
      : data === undefined
        ? undefined
        : JSON.stringify(data)
  if (body && !(body instanceof FormData))
    headers["Content-Type"] = "application/json"
  let response: Response
  try {
    response = await fetch(`/api${path}`, {
      method,
      headers,
      body,
      credentials: "same-origin",
    })
  } catch {
    throw new APIError(
      "Нет связи с сервером. Проверьте подключение и повторите.",
      0
    )
  }
  const result = await response
    .json()
    .catch(() => ({ detail: "Не удалось прочитать ответ сервера" }))
  if (!response.ok) {
    if (response.status === 401 && !path.startsWith("/auth/"))
      window.dispatchEvent(new Event("auth-expired"))
    const message = Array.isArray(result.detail)
      ? "Проверьте заполненные поля и выбранные материалы"
      : result.detail || "Не удалось выполнить запрос"
    throw new APIError(message, response.status)
  }
  return result as T
}
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "Не удалось выполнить запрос"
export function useQuery<T>(path: string | null, poll = 0) {
  const [state, setState] = useState<{
    key: string
    data: T | null
    error: string | null
  }>({ key: "", data: null, error: null })
  const [revision, setRevision] = useState(0)
  const key = `${path}:${revision}`
  useEffect(() => {
    let alive = true,
      pending = false
    async function load() {
      if (!path || pending) return
      pending = true
      try {
        const data = await api<T>(path)
        if (alive) setState({ key, data, error: null })
      } catch (e) {
        if (alive)
          setState((previous) => ({
            key,
            data: previous.key === key ? previous.data : null,
            error: errorText(e),
          }))
      } finally {
        pending = false
      }
    }
    void load()
    const timer = poll ? window.setInterval(() => void load(), poll) : undefined
    return () => {
      alive = false
      if (timer) window.clearInterval(timer)
    }
  }, [path, poll, key])
  return {
    data: state.key === key ? state.data : null,
    error: state.key === key ? state.error : null,
    loading: !!path && state.key !== key,
    refetch: () => setRevision((x) => x + 1),
  }
}
export function navigate(path: string) {
  window.location.hash = path
}
