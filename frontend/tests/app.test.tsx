import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"
import App from "../src/App"

const user = {
  id: 1,
  username: "child",
  display_name: "Дочка",
  csrf_token: "token",
}
function server(
  routes: Record<string, unknown | ((init?: RequestInit) => unknown)>
) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const key = `${init?.method || "GET"} ${path}`
      const route = routes[key]
      if (route === undefined) throw new Error(`Unexpected request ${key}`)
      const data = typeof route === "function" ? route(init) : route
      return new Response(JSON.stringify(data), {
        status:
          typeof data === "object" && data && "http_status" in data
            ? Number(data.http_status)
            : typeof data === "object" && data && "detail" in data
              ? 401
              : 200,
        headers: { "Content-Type": "application/json" },
      })
    })
  )
}

test("shows a login error without losing the entered username", async () => {
  server({
    "GET /api/auth/me": { detail: "Войдите в аккаунт" },
    "POST /api/auth/login": { detail: "Неверный логин или пароль" },
  })
  render(<App />)
  await userEvent.type(await screen.findByLabelText("Логин"), "child")
  await userEvent.type(screen.getByLabelText("Пароль"), "wrong-password")
  await userEvent.click(screen.getByRole("button", { name: "Войти" }))
  expect(await screen.findByText("Неверный логин или пароль")).toBeVisible()
  expect(screen.getByLabelText("Логин")).toHaveValue("child")
})

test("reloads a study session when a second tab has already answered", async () => {
  window.location.hash = "#study/7"
  const card = {
    id: 1,
    topic_id: 1,
    question: "Первый вопрос",
    mode: "quiz",
    options: ["Нил", "Дон"],
    version: 1,
    status: "saved",
    sources: [],
    revealed: false,
  }
  const session = {
    id: 7,
    topic_ids: [1],
    topic_names: ["Египет"],
    mode: "quiz",
    position: 0,
    status: "active",
    count: 2,
    answered: 0,
    correct: 0,
    card,
  }
  let loads = 0
  server({
    "GET /api/auth/me": user,
    "GET /api/study/7": () =>
      ++loads === 1
        ? session
        : {
            ...session,
            position: 1,
            answered: 1,
            card: { ...card, id: 2, question: "Следующий вопрос" },
          },
    "GET /api/study/7/explanations?position=0": [],
    "GET /api/study/7/explanations?position=1": [],
    "GET /api/study/7/explanation-jobs?position=0": [],
    "GET /api/study/7/explanation-jobs?position=1": [],
    "POST /api/study/7/answer": { http_status: 409, detail: "Уже сохранено" },
  })
  render(<App />)
  await userEvent.click(await screen.findByRole("button", { name: /Нил/ }))
  await userEvent.click(screen.getByRole("button", { name: "Проверить ответ" }))
  expect(await screen.findByText("Следующий вопрос")).toBeVisible()
  expect(screen.queryByText("Первый вопрос")).not.toBeInTheDocument()
})

test("edits a generated draft and saves only selected cards", async () => {
  window.location.hash = "#generate?job=3"
  let card = {
    id: 1,
    topic_id: 1,
    question: "Исходный вопрос",
    answer: "Нил",
    mode: "flashcard",
    options: [],
    correct_index: null,
    version: 1,
    status: "draft",
    sources: [{ document_id: 1, page: 1, name: "Учебник.pdf" }],
  }
  const job = {
    id: 3,
    kind: "generate",
    status: "succeeded",
    error: null,
    created: "2026-10-10T10:00:00",
    result: { card_ids: [1], warnings: [] },
  }
  server({
    "GET /api/auth/me": user,
    "GET /api/topics": [],
    "GET /api/subjects": [],
    "GET /api/jobs": [job],
    "GET /api/jobs/3": job,
    "GET /api/cards?job_id=3": () => [card],
    "PATCH /api/cards/1": (init) => {
      const body = JSON.parse(String(init?.body))
      card = { ...card, ...body, version: 2 }
      return card
    },
    "POST /api/cards/save": (init) => {
      expect(JSON.parse(String(init?.body)).card_ids).toEqual([1])
      card = { ...card, status: "saved" }
      return { saved: 1 }
    },
  })
  render(<App />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Изменить карточку" })
  )
  await userEvent.clear(screen.getByLabelText("Вопрос"))
  await userEvent.type(screen.getByLabelText("Вопрос"), "Главная река Египта?")
  await userEvent.click(
    screen.getByRole("button", { name: "Сохранить изменения" })
  )
  expect(await screen.findByText("Главная река Египта?")).toBeVisible()
  await userEvent.click(
    screen.getByRole("checkbox", { name: "Выбрать: Главная река Египта?" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Сохранить выбранные (1)" })
  )
  expect(await screen.findByText("Сохранена")).toBeVisible()
})

test("generation requires explicitly selected topics", async () => {
  window.location.hash = "#generate"
  server({
    "GET /api/auth/me": user,
    "GET /api/topics": [
      {
        id: 1,
        subject_id: 1,
        name: "Египет",
        version: 1,
        card_count: 0,
        document_count: 1,
      },
    ],
    "GET /api/subjects": [{ id: 1, name: "История", topic_count: 1 }],
    "GET /api/jobs": [],
  })
  render(<App />)
  const button = await screen.findByRole("button", { name: "Создать карточки" })
  expect(button).toBeDisabled()
  await userEvent.click(await screen.findByRole("checkbox", { name: /Египет/ }))
  expect(button).toBeEnabled()
})

test("quiz waits for saved answer before allowing the next card", async () => {
  window.location.hash = "#study/7"
  const card = {
    id: 1,
    topic_id: 1,
    question: "Главная река Египта?",
    mode: "quiz",
    options: ["Нил", "Дон"],
    version: 1,
    status: "saved",
    sources: [],
    revealed: false,
  }
  const session = {
    id: 7,
    topic_ids: [1],
    topic_names: ["Египет"],
    mode: "quiz",
    position: 0,
    status: "active",
    count: 2,
    answered: 0,
    correct: 0,
    card,
  }
  let finish: ((value: unknown) => void) | undefined
  server({
    "GET /api/auth/me": user,
    "GET /api/study/7": session,
    "GET /api/study/7/explanations?position=0": [],
    "GET /api/study/7/explanation-jobs?position=0": [],
    "GET /api/jobs": [],
  })
  const original = globalThis.fetch
  vi.stubGlobal("fetch", (path: string, init?: RequestInit) => {
    if (path === "/api/study/7/answer")
      return new Promise<Response>((resolve) => {
        finish = () =>
          resolve(
            new Response(
              JSON.stringify({
                session_id: 7,
                position: 0,
                correct: true,
                card: { ...card, answer: "Нил", correct_index: 0 },
                next_position: 1,
              })
            )
          )
      })
    return original(path, init)
  })
  render(<App />)
  await userEvent.click(await screen.findByRole("button", { name: /Нил/ }))
  await userEvent.click(screen.getByRole("button", { name: "Проверить ответ" }))
  expect(
    screen.queryByRole("button", { name: "Следующая карточка" })
  ).not.toBeInTheDocument()
  await waitFor(() => expect(finish).toBeDefined())
  finish!({})
  expect(
    await screen.findByRole("button", { name: "Следующая карточка" })
  ).toBeEnabled()
  expect(await screen.findByText("Верно!")).toBeVisible()
})

test("starts study with only explicitly selected topics and chosen format", async () => {
  window.location.hash = "#library"
  let submitted: unknown
  server({
    "GET /api/auth/me": user,
    "GET /api/subjects": [{ id: 1, name: "История", topic_count: 3 }],
    "GET /api/topics": [1, 2, 3].map((id) => ({
      id,
      subject_id: 1,
      name: `Тема ${id}`,
      version: 1,
      card_count: 2,
      document_count: 1,
    })),
    "POST /api/study": (init) => {
      submitted = JSON.parse(String(init?.body))
      return { id: 8 }
    },
    "GET /api/study/8": {
      id: 8,
      topic_names: ["Тема 1", "Тема 3"],
      mode: "quiz",
      status: "completed",
      count: 4,
      correct: 4,
    },
  })
  render(<App />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать темы для повторения" })
  )
  const start = screen.getByRole("button", { name: "Начать занятие" })
  expect(start).toBeDisabled()
  await userEvent.click(screen.getByRole("checkbox", { name: /Тема 1/ }))
  await userEvent.click(screen.getByRole("checkbox", { name: /Тема 3/ }))
  await userEvent.click(screen.getByRole("button", { name: "Тест" }))
  await userEvent.click(start)
  await waitFor(() =>
    expect(submitted).toEqual({ topic_ids: [1, 3], mode: "quiz" })
  )
  expect(await screen.findByText("Ещё один шаг вперёд")).toBeVisible()
})

test("skip link focuses content without leaving the current route", async () => {
  window.location.hash = "#history"
  server({ "GET /api/auth/me": user, "GET /api/study": [] })
  render(<App />)
  await userEvent.click(
    await screen.findByRole("link", { name: "К содержимому" })
  )
  expect(window.location.hash).toBe("#history")
  expect(document.getElementById("main")).toHaveFocus()
})

test("ambiguous flashcard save retries the original grade without offering a new grade", async () => {
  window.location.hash = "#study/9"
  const card = {
    id: 1,
    topic_id: 1,
    question: "Что такое Нил?",
    answer: "Река",
    mode: "flashcard",
    options: [],
    version: 1,
    status: "saved",
    sources: [],
    revealed: true,
  }
  const session = {
    id: 9,
    topic_ids: [1],
    topic_names: ["Египет"],
    mode: "flashcard",
    position: 0,
    status: "active",
    count: 1,
    answered: 0,
    correct: 0,
    card,
  }
  let first: unknown
  let saves = 0
  server({
    "GET /api/auth/me": user,
    "GET /api/study/9": session,
    "GET /api/study/9/explanations?position=0": [],
    "GET /api/study/9/explanation-jobs?position=0": [],
    "POST /api/study/9/answer": (init) => {
      const body = JSON.parse(String(init?.body))
      if (++saves === 1) {
        first = body
        throw new Error("Соединение потеряно")
      }
      expect(body).toEqual(first)
      expect(body.remembered).toBe(false)
      return {
        session_id: 9,
        position: 0,
        correct: false,
        card,
        next_position: 1,
      }
    },
  })
  render(<App />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Повторить" })
  )
  expect(
    await screen.findByText(
      "Нет связи с сервером. Проверьте подключение и повторите."
    )
  ).toBeVisible()
  expect(
    screen.queryByRole("button", { name: "Помню" })
  ).not.toBeInTheDocument()
  await userEvent.click(
    screen.getByRole("button", { name: "Повторить сохранение ответа" })
  )
  expect(
    await screen.findByRole("button", { name: "Результат занятия" })
  ).toBeEnabled()
})

test("changing subject cannot submit a previously selected hidden topic", async () => {
  window.location.hash = "#library"
  server({
    "GET /api/auth/me": user,
    "GET /api/subjects": [
      { id: 1, name: "История", topic_count: 1 },
      { id: 2, name: "Биология", topic_count: 1 },
    ],
    "GET /api/topics": [
      {
        id: 1,
        subject_id: 1,
        name: "Египет",
        card_count: 2,
        document_count: 1,
      },
      {
        id: 2,
        subject_id: 2,
        name: "Растения",
        card_count: 2,
        document_count: 1,
      },
    ],
  })
  render(<App />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Выбрать темы для повторения" })
  )
  await userEvent.click(screen.getByRole("checkbox", { name: "Египет" }))
  await userEvent.keyboard("{Escape}")
  await userEvent.click(screen.getByRole("link", { name: /Биология/ }))
  await userEvent.click(
    screen.getByRole("button", { name: "Выбрать темы для повторения" })
  )
  expect(
    screen.queryByRole("checkbox", { name: "Египет" })
  ).not.toBeInTheDocument()
  expect(screen.getByRole("button", { name: "Начать занятие" })).toBeDisabled()
})
