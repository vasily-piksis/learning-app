import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import History from "../src/features/History"
import type { StudySession } from "../src/types"

const initial: StudySession[] = [
  {
    id: 3,
    topic_ids: [1],
    topic_names: ["Египет"],
    mode: "quiz",
    position: 0,
    status: "active",
    count: 2,
    answered: 0,
    correct: 0,
    created: "2026-10-13T08:00:00",
  },
  {
    id: 2,
    topic_ids: [2],
    topic_names: ["Польский"],
    mode: "flashcard",
    position: 1,
    status: "completed",
    count: 1,
    answered: 1,
    correct: 1,
    created: "2026-10-12T08:00:00",
  },
  {
    id: 1,
    topic_ids: [3],
    topic_names: ["Литовский"],
    mode: "quiz",
    position: 1,
    status: "completed",
    count: 1,
    answered: 1,
    correct: 0,
    created: "2026-10-11T08:00:00",
  },
]

beforeEach(() => localStorage.setItem("learning-ui-language", "ru"))

function server(failOnce = false, staleOnce = false) {
  let records = [...initial]
  let deletionAttempts = 0
  const requests: number[][] = []
  vi.stubGlobal("fetch", async (path: string, init: RequestInit) => {
    if (path === "/api/study" && init.method === "GET")
      return Response.json(records)
    if (path === "/api/study/delete" && init.method === "POST") {
      const ids = JSON.parse(String(init.body)).session_ids as number[]
      requests.push(ids)
      if (staleOnce) {
        staleOnce = false
        records = records.filter((s) => s.id !== ids[0])
        return Response.json(
          { detail: "Занятие не найдено. Обновите историю" },
          { status: 404 }
        )
      }
      if (failOnce && deletionAttempts++ === 0)
        return Response.json(
          { detail: "Сервер временно недоступен" },
          { status: 503 }
        )
      records = records.filter((s) => !ids.includes(s.id))
      return Response.json({ deleted_count: ids.length })
    }
    throw new Error(`Unexpected request: ${init.method} ${path}`)
  })
  return requests
}

test("bulk deletion needs confirmation and removes only selected sessions", async () => {
  const requests = server()
  render(<History />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать занятия" })
  )
  expect(
    screen.getByRole("button", { name: "Удалить выбранные (0)" })
  ).toBeDisabled()
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать занятие #3" })
  )
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать занятие #2" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Удалить выбранные (2)" })
  )
  const dialog = screen.getByRole("dialog")
  expect(within(dialog).getByText("Будет удалено занятий: 2.")).toBeVisible()
  expect(requests).toEqual([])
  await userEvent.click(within(dialog).getByRole("button", { name: "Отмена" }))
  expect(
    screen.getByRole("checkbox", { name: "Выбрать занятие #3" })
  ).toBeChecked()
  expect(requests).toEqual([])
  await userEvent.click(
    screen.getByRole("button", { name: "Удалить выбранные (2)" })
  )
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" })
  )
  await waitFor(() =>
    expect(screen.queryByText("Египет")).not.toBeInTheDocument()
  )
  expect(screen.queryByText("Польский")).not.toBeInTheDocument()
  expect(screen.getByText("Литовский")).toBeVisible()
  expect(requests).toEqual([[3, 2]])
  expect(screen.getByRole("status")).toHaveTextContent("Удалено занятий: 2.")
})

test("failed deletion preserves selection and can be retried", async () => {
  server(true)
  render(<History />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать занятия" })
  )
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать занятие #1" })
  )
  const selectedCheckbox = screen.getByRole("checkbox", {
    name: "Выбрать занятие #1",
  })
  await userEvent.click(
    screen.getByRole("button", { name: "Удалить выбранные (1)" })
  )
  const dialog = screen.getByRole("dialog")
  await userEvent.click(within(dialog).getByRole("button", { name: "Удалить" }))
  expect(
    await within(dialog).findByText("Сервер временно недоступен")
  ).toBeVisible()
  expect(selectedCheckbox).toBeChecked()
  expect(screen.getByText("Литовский")).toBeVisible()
  await userEvent.click(within(dialog).getByRole("button", { name: "Удалить" }))
  await waitFor(() =>
    expect(screen.queryByText("Литовский")).not.toBeInTheDocument()
  )
})

test("select all shown, clear selection and delete to empty history", async () => {
  server()
  render(<History />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать занятия" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Выбрать все показанные" })
  )
  expect(
    screen
      .getAllByRole("checkbox")
      .every((c) => c.getAttribute("aria-checked") === "true")
  ).toBe(true)
  await userEvent.click(screen.getByRole("button", { name: "Снять выделение" }))
  expect(
    screen.getByRole("button", { name: "Удалить выбранные (0)" })
  ).toBeDisabled()
  await userEvent.click(
    screen.getByRole("button", { name: "Выбрать все показанные" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Удалить выбранные (3)" })
  )
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" })
  )
  expect(await screen.findByText("Первое занятие ещё впереди")).toBeVisible()
  expect(
    screen.queryByRole("button", { name: "Выбрать занятия" })
  ).not.toBeInTheDocument()
})

test("leaving selection mode clears previous choices", async () => {
  server()
  render(<History />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать занятия" })
  )
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать занятие #2" })
  )
  await userEvent.click(screen.getByRole("button", { name: "Завершить выбор" }))
  await userEvent.click(screen.getByRole("button", { name: "Выбрать занятия" }))
  expect(
    screen.getByRole("checkbox", { name: "Выбрать занятие #2" })
  ).not.toBeChecked()
})

test("deletion in another tab refreshes history and clears stale selection", async () => {
  server(false, true)
  render(<History />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать занятия" })
  )
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать занятие #3" })
  )
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать занятие #2" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Удалить выбранные (2)" })
  )
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" })
  )
  expect(
    await screen.findByText("Занятие не найдено. Обновите историю")
  ).toBeVisible()
  await waitFor(() =>
    expect(screen.queryByText("Египет")).not.toBeInTheDocument()
  )
  expect(screen.getByText("Польский")).toBeVisible()
  expect(
    screen.getByRole("button", { name: "Удалить выбранные (0)" })
  ).toBeDisabled()
})
