import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import RegenerateQuestion from "../src/features/exercises/RegenerateQuestion"
import type { Card } from "../src/types"
const original: Card = {
  id: 1,
  topic_id: 1,
  question: "Old question",
  answer: "Nil",
  mode: "quiz",
  question_type: "choice",
  exercise: null,
  language: "pl",
  options: ["Nil", "Don"],
  correct_indices: [0],
  correct_index: 0,
  version: 2,
  status: "saved",
  sources: [{ document_id: 1, page: 1 }],
}
const candidate = {
  topic_id: 1,
  question: "New question",
  answer: "Nil",
  mode: "quiz",
  question_type: "choice",
  exercise: null,
  language: "pl",
  options: ["Nil", "Don"],
  correct_indices: [0],
  correct_index: 0,
  sources: [{ document_id: 1, page: 1 }],
}
beforeEach(() => localStorage.setItem("learning-ui-language", "ru"))
function server(conflict = false) {
  const calls: {
    path: string
    method: string
    body: Record<string, unknown> | null
  }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push({
        path,
        method: init?.method || "GET",
        body: init?.body ? JSON.parse(String(init.body)) : null,
      })
      const job = {
        id: 9,
        kind: "regenerate",
        status: "succeeded",
        error: null,
        topic_ids: [1],
        result: { candidate, base_version: 2, card_id: 1 },
      }
      return new Response(
        JSON.stringify(
          path.endsWith("/apply-regeneration")
            ? conflict
              ? { detail: "Карточка изменена в другой вкладке" }
              : { ...original, question: "Edited candidate", version: 3 }
            : path.endsWith("/discard-regeneration")
              ? { ...job, status: "cancelled", result: { discarded: true } }
              : job
        ),
        {
          status: path.endsWith("/apply-regeneration") && conflict ? 409 : 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    })
  )
  return calls
}
test("regeneration previews without replacement; candidate editing stays local until explicit apply", async () => {
  const calls = server(),
    saved = vi.fn()
  render(<RegenerateQuestion card={original} onSaved={saved} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Перегенерировать вопрос" })
  )
  await screen.findByText("New question")
  expect(
    calls.filter(
      (c) => c.path.endsWith("/apply-regeneration") || c.method === "PATCH"
    )
  ).toEqual([])
  await userEvent.click(
    screen.getByRole("button", { name: "Изменить карточку" })
  )
  const input = screen.getByRole("textbox", { name: "Вопрос", exact: true })
  await userEvent.clear(input)
  await userEvent.type(input, "Edited candidate")
  await userEvent.click(
    screen.getByRole("button", { name: "Обновить кандидат" })
  )
  expect(calls.some((c) => c.method === "PATCH")).toBe(false)
  await userEvent.click(
    screen.getByRole("button", { name: "Применить вариант" })
  )
  await waitFor(() => expect(saved).toHaveBeenCalledOnce())
  expect(
    calls.find((c) => c.path.endsWith("/apply-regeneration"))?.body
  ).toMatchObject({
    candidate: {
      question: "Edited candidate",
      language: "pl",
      question_type: "choice",
      topic_id: 1,
    },
  })
})
test("discard is explicit and leaves original unchanged", async () => {
  const calls = server(),
    saved = vi.fn()
  render(<RegenerateQuestion card={original} onSaved={saved} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Перегенерировать вопрос" })
  )
  await screen.findByText("New question")
  await userEvent.click(
    screen.getByRole("button", { name: "Отклонить вариант" })
  )
  await waitFor(() =>
    expect(calls.some((c) => c.path.endsWith("/discard-regeneration"))).toBe(
      true
    )
  )
  expect(saved).not.toHaveBeenCalled()
  expect(calls.some((c) => c.path.endsWith("/apply-regeneration"))).toBe(false)
})
test("version conflict keeps the preview and does not announce successful apply", async () => {
  server(true)
  const saved = vi.fn()
  render(<RegenerateQuestion card={original} onSaved={saved} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Перегенерировать вопрос" })
  )
  await screen.findByText("New question")
  await userEvent.click(
    screen.getByRole("button", { name: "Применить вариант" })
  )
  expect(
    await screen.findByText("Карточка изменена в другой вкладке")
  ).toBeVisible()
  expect(screen.getByText("New question")).toBeVisible()
  expect(saved).not.toHaveBeenCalled()
})
test("another variant is an explicit new request with a distinct idempotency key", async () => {
  const calls = server()
  render(<RegenerateQuestion card={original} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Перегенерировать вопрос" })
  )
  await screen.findByText("New question")
  await userEvent.click(screen.getByRole("button", { name: "Другой вариант" }))
  await waitFor(() =>
    expect(calls.filter((c) => c.path.endsWith("/regenerate"))).toHaveLength(2)
  )
  const requests = calls.filter((c) => c.path.endsWith("/regenerate"))
  expect(requests[1].body).toMatchObject({ version: 2, another_variant: true })
  expect(requests[1].body?.idempotency_key).not.toBe(
    requests[0].body?.idempotency_key
  )
})

test("closing and reopening the same preview retains locally edited candidate until apply", async () => {
  server()
  render(<RegenerateQuestion card={original} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Перегенерировать вопрос" })
  )
  await screen.findByText("New question")
  await userEvent.click(
    screen.getByRole("button", { name: "Изменить карточку" })
  )
  const input = screen.getByRole("textbox", { name: "Вопрос", exact: true })
  await userEvent.clear(input)
  await userEvent.type(input, "Local edited question")
  await userEvent.click(
    screen.getByRole("button", { name: "Обновить кандидат" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Закрыть", exact: true })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Перегенерировать вопрос" })
  )
  expect(await screen.findByText("Local edited question")).toBeVisible()
})
