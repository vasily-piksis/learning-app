import { act, renderHook, waitFor } from "@testing-library/react"
import { expect, test, vi } from "vitest"
import { useQuery } from "../src/api"

test("keeps loaded data visible while refreshing the same resource", async () => {
  let finish: (response: Response) => void = () => {}
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 1 }])))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve
          })
      )
  )
  const { result } = renderHook(() => useQuery<{ id: number }[]>("/topics"))
  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  act(() => result.current.refetch())
  expect(result.current.data).toEqual([{ id: 1 }])
  expect(result.current.loading).toBe(false)
  await act(async () =>
    finish(new Response(JSON.stringify([{ id: 1 }, { id: 2 }])))
  )
  await waitFor(() => expect(result.current.data).toHaveLength(2))
})

test("does not show another resource's data after navigation", async () => {
  let finish: (response: Response) => void = () => {}
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: 1 }])))
      .mockImplementationOnce(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve
          })
      )
  )
  const { result, rerender } = renderHook(({ path }) => useQuery(path), {
    initialProps: { path: "/topics/1/documents" },
  })
  await waitFor(() => expect(result.current.data).toEqual([{ id: 1 }]))
  rerender({ path: "/topics/2/documents" })
  expect(result.current.data).toBeNull()
  expect(result.current.loading).toBe(true)
  await act(async () => finish(new Response(JSON.stringify([{ id: 2 }]))))
  await waitFor(() => expect(result.current.data).toEqual([{ id: 2 }]))
})

test("structured API errors retain the human-readable message", async () => {
  const { api, APIError } = await import("../src/api")
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              message: "Подготовьте задания выбранного типа",
              missing_pairs: [{ topic_id: 2, question_type: "written" }],
            },
          }),
          { status: 422, headers: { "Content-Type": "application/json" } }
        )
    )
  )
  await expect(api("/study", "POST", {})).rejects.toThrow(
    "Подготовьте задания выбранного типа"
  )
  await expect(api("/study", "POST", {})).rejects.toBeInstanceOf(APIError)
})
