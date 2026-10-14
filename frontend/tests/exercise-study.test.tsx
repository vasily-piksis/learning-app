import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { beforeEach, expect, test, vi } from "vitest"
import ExerciseInput from "../src/features/exercises/ExerciseInput"
import StartStudy, { Preparation } from "../src/features/StartStudy"
import Study from "../src/features/Study"
import type {
  Card,
  ExerciseSubmission,
  Topic,
  MethodAvailability,
} from "../src/types"

beforeEach(() => localStorage.setItem("learning-ui-language", "ru"))
const card = (
  type: Card["question_type"],
  exercise: Card["exercise"]
): Card => ({
  id: 1,
  topic_id: 1,
  question: "Uzupełnij",
  question_type: type,
  exercise,
  mode: "quiz",
  options: [],
  version: 1,
  status: "saved",
  sources: [],
})
function Input({ card: current }: { card: Card }) {
  const [value, setValue] = useState<ExerciseSubmission | null>(null)
  return (
    <>
      <ExerciseInput
        card={current}
        value={value}
        onChange={setValue}
        disabled={false}
      />
      <output data-testid="submission">{JSON.stringify(value)}</output>
    </>
  )
}
test("written input sends the original-language text", async () => {
  render(<Input card={card("written", { case_sensitive: false })} />)
  await userEvent.type(
    screen.getByRole("textbox", { name: "Твой ответ" }),
    "Ąžuolas"
  )
  expect(screen.getByTestId("submission")).toHaveTextContent('"text":"Ąžuolas"')
})
test.each(["gap", "ending"] as const)(
  "%s labels every slot and preserves IDs",
  async (type) => {
    render(
      <Input
        card={card(type, {
          segments: [{ text: "Ąžuol" }, { gap_id: "x" }],
          gaps: [{ id: "x" }],
          case_sensitive: false,
        })}
      />
    )
    await userEvent.type(
      screen.getByRole("textbox", { name: "Пропуск 1" }),
      "as"
    )
    expect(screen.getByTestId("submission")).toHaveTextContent(
      '"gap_answers":{"x":"as"}'
    )
  }
)
test("matching permits choosing and undoing a pair by IDs", async () => {
  render(
    <Input
      card={card("matching", {
        left: [
          { id: "l1", text: "stalas" },
          { id: "l2", text: "namas" },
        ],
        right: [
          { id: "r1", text: "дом" },
          { id: "r2", text: "стол" },
        ],
      })}
    />
  )
  await userEvent.click(
    screen.getByRole("button", { name: "stalas", exact: true })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "стол", exact: true })
  )
  expect(screen.getByTestId("submission")).toHaveTextContent(
    '"left_id":"l1","right_id":"r2"'
  )
  await userEvent.click(screen.getByRole("button", { name: /Отменить пару/ }))
  expect(screen.getByTestId("submission")).toHaveTextContent('"pairs":[]')
})
test("ordering handles duplicate tokens, return, clear and keyboard activation", async () => {
  render(
    <Input
      card={card("ordering", {
        tokens: [
          { id: "a", text: "very" },
          { id: "b", text: "very" },
          { id: "c", text: "good" },
        ],
      })}
    />
  )
  const tokens = screen.getAllByRole("button", { name: "very", exact: true })
  tokens[0].focus()
  await userEvent.keyboard("{Enter}")
  await userEvent.click(
    screen.getByRole("button", { name: "very", exact: true })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "good", exact: true })
  )
  expect(screen.getByTestId("submission")).toHaveTextContent(
    '"order":["a","b","c"]'
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Вернуть слово 1: very" })
  )
  expect(
    screen.getByRole("button", { name: "very", exact: true })
  ).toBeVisible()
  await userEvent.click(
    screen.getByRole("button", { name: "Очистить предложение" })
  )
  expect(screen.getByTestId("submission")).toHaveTextContent('"order":[]')
})
const ready = (count = 0): MethodAvailability => ({
  ready_count: count,
  draft_count: 0,
  needs_options_count: 0,
  preparation_job_id: null,
  preparation_status: null,
  has_ready_materials: true,
  last_outcome: null,
})
const topic: Topic = {
  id: 1,
  name: "Polski",
  subject_id: 1,
  version: 1,
  card_count: 3,
  document_count: 1,
  practice_availability: {
    flashcard: ready(3),
    choice: ready(1),
    written: ready(2),
    gap: ready(),
    ending: ready(),
    matching: ready(),
    ordering: ready(),
  },
}
async function selectMethod(name: string) {
  const selector = screen.getByRole("combobox", { name: "Способ проверки" })
  selector.focus()
  await userEvent.keyboard("{Enter}")
  await userEvent.click(
    await screen.findByRole("option", { name: new RegExp(name) })
  )
}
test("selector defaults to flashcards and zero-count method opens preparation without AI", async () => {
  const fetch = vi.fn()
  vi.stubGlobal("fetch", fetch)
  render(<StartStudy topicIds={[1]} topics={[topic]} />)
  expect(screen.getByRole("combobox")).toHaveTextContent("Флеш-карты")
  expect(
    screen.queryByRole("button", { name: "Тест", exact: true })
  ).not.toBeInTheDocument()
  await selectMethod("Окончания")
  await userEvent.click(
    screen.getByRole("button", { name: "Подготовить задания" })
  )
  expect(window.location.hash).toBe("#library/topic/1/create/ending")
  expect(fetch).not.toHaveBeenCalled()
})
test("selected method sends exact topics and typed start request", async () => {
  const requests: unknown[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      requests.push(JSON.parse(String(init?.body)))
      return new Response(JSON.stringify({ id: 7 }), {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  render(<StartStudy topicIds={[1]} topics={[topic]} />)
  await selectMethod("Письменный ответ")
  await userEvent.click(screen.getByRole("button", { name: "Начать занятие" }))
  expect(requests).toEqual([
    { topic_ids: [1], mode: "quiz", question_types: ["written"] },
  ])
})
test("preparation preview does not start a paid or study request; acceptance and discard are explicit", async () => {
  const calls: string[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push(`${init?.method || "GET"} ${path}`)
      if (path === "/api/jobs/4")
        return new Response(
          JSON.stringify({
            id: 4,
            kind: "prepare_quiz",
            status: "succeeded",
            topic_ids: [1],
            result: {
              candidates: [
                {
                  card_id: 1,
                  version: 1,
                  options: ["stalas", "namas"],
                  correct_indices: [0],
                  correct_index: 0,
                },
              ],
              applied_card_ids: [],
            },
          }),
          { headers: { "Content-Type": "application/json" } }
        )
      if (path === "/api/cards")
        return new Response(JSON.stringify([card("choice", null)]), {
          headers: { "Content-Type": "application/json" },
        })
      if (path.endsWith("/save-preparation"))
        return new Response(JSON.stringify({}), {
          headers: { "Content-Type": "application/json" },
        })
      throw new Error(path)
    })
  )
  render(<Preparation id={4} />)
  expect(await screen.findByText("stalas")).toBeVisible()
  expect(calls.filter((c) => c.startsWith("POST"))).toEqual([])
  await userEvent.click(screen.getByRole("checkbox", { name: /Выбрать:/ }))
  await userEvent.click(
    screen.getByRole("button", { name: /Сохранить выбранные/ })
  )
  await waitFor(() =>
    expect(calls).toContain("POST /api/jobs/4/save-preparation")
  )
  expect(calls).not.toContain("POST /api/study")
})
test("written check waits for a complete answer and retains payload and key after network failure", async () => {
  const posts: unknown[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/study/1")
        return new Response(
          JSON.stringify({
            id: 1,
            topic_ids: [1],
            topic_names: ["Polski"],
            mode: "quiz",
            position: 0,
            count: 1,
            answered: 0,
            status: "active",
            card: card("written", { case_sensitive: false }),
          }),
          { headers: { "Content-Type": "application/json" } }
        )
      if (path.endsWith("/answer")) {
        posts.push(JSON.parse(String(init?.body)))
        if (posts.length === 1) throw new Error("Network")
        return new Response(
          JSON.stringify({
            correct: false,
            card: {
              ...card("written", {
                accepted_answers: ["stalas"],
                case_sensitive: false,
              }),
              answer: "stalas",
            },
            submission: { text: "wrong" },
            parts: [],
          }),
          { headers: { "Content-Type": "application/json" } }
        )
      }
      return new Response("[]", {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  render(<Study id={1} />)
  const check = await screen.findByRole("button", { name: "Проверить ответ" })
  expect(check).toBeDisabled()
  await userEvent.type(
    screen.getByRole("textbox", { name: "Твой ответ" }),
    "wrong"
  )
  await userEvent.click(check)
  expect(screen.getByRole("textbox", { name: "Твой ответ" })).toBeDisabled()
  await userEvent.click(check)
  await screen.findByText("Неверно. Правильный ответ:")
  expect(posts[0]).toEqual(posts[1])
  expect(posts[0]).toMatchObject({
    text: "wrong",
    idempotency_key: expect.any(String),
  })
})

test("mixed practice starts with common types and cannot start with an empty filter", async () => {
  const second = structuredClone(topic)
  second.id = 2
  second.name = "Lietuvių"
  second.practice_availability!.choice = ready()
  render(<StartStudy topicIds={[1, 2]} topics={[topic, second]} />)
  await selectMethod("Смешанная практика")
  const written = screen.getByRole("checkbox", { name: /Письменный ответ/ })
  expect(written).toBeChecked()
  expect(
    screen.getByRole("checkbox", { name: /Выбор ответа/ })
  ).not.toBeChecked()
  await userEvent.click(written)
  expect(
    screen.getByRole("button", { name: "Подготовить задания" })
  ).toBeDisabled()
  await userEvent.click(screen.getByRole("checkbox", { name: /Выбор ответа/ }))
  expect(screen.getByText(/Подготовка нужна:/)).toHaveTextContent("Lietuvių")
  await userEvent.click(
    screen.getByRole("button", { name: "Подготовить задания" })
  )
  expect(window.location.hash).toBe("#library/topic/2/create/choice")
})
test("opening already running preparation reuses its job and does not create another request", async () => {
  const current = structuredClone(topic)
  current.practice_availability!.ending = {
    ...ready(),
    preparation_job_id: 9,
    preparation_status: "running",
  }
  const calls: string[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      calls.push(`${init?.method || "GET"} ${path}`)
      return new Response(JSON.stringify({ id: 9, kind: "generate" }), {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  render(<StartStudy topicIds={[1]} topics={[current]} />)
  await selectMethod("Окончания")
  await userEvent.click(
    screen.getByRole("button", { name: "Открыть подготовку" })
  )
  await waitFor(() => expect(window.location.hash).toBe("#generation/9"))
  expect(calls).toEqual(["GET /api/jobs/9"])
})
test("gap feedback identifies incorrect parts in red, text and accessible invalid state", () => {
  const current = card("gap", {
    segments: [
      { text: "A " },
      { gap_id: "x" },
      { text: " B " },
      { gap_id: "y" },
    ],
    gaps: [{ id: "x" }, { id: "y" }],
    case_sensitive: false,
  })
  render(
    <ExerciseInput
      card={current}
      value={{ gap_answers: { x: "right", y: "wrong" } }}
      onChange={() => {}}
      disabled
      feedback={{
        correct: false,
        session_id: 1,
        position: 0,
        next_position: 1,
        card: current,
        parts: [
          { id: "x", correct: true },
          { id: "y", correct: false },
        ],
        message_code: "incompatible_combination",
      }}
    />
  )
  expect(screen.getByRole("textbox", { name: "Пропуск 2" })).toHaveAttribute(
    "aria-invalid",
    "true"
  )
  expect(screen.getByRole("textbox", { name: "Пропуск 2" })).toHaveClass(
    "border-destructive"
  )
  expect(screen.getByText("Неверный ответ")).toBeVisible()
  expect(screen.getByText("Верных частей: 1 из 2")).toBeVisible()
  expect(screen.getByText(/допустимы по отдельности/)).toBeVisible()
})

test("choice history renders the saved submission once with legacy fallback", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (path: string) =>
        new Response(
          JSON.stringify(
            path === "/api/study/3"
              ? {
                  id: 3,
                  mode: "quiz",
                  practice_method: "choice",
                  topic_ids: [1],
                  topic_names: ["Polski"],
                  status: "completed",
                  count: 1,
                  correct: 0,
                  answered: 1,
                  review: [
                    {
                      position: 0,
                      card: {
                        ...card("choice", null),
                        question: "Table?",
                        answer: "stół",
                        options: ["stół", "krzesło"],
                      },
                      correct: false,
                      choice: null,
                      choices: [1],
                      submission: { choices: [1] },
                    },
                  ],
                }
              : []
          ),
          { headers: { "Content-Type": "application/json" } }
        )
    )
  )
  render(<Study id={3} />)
  await screen.findByText("Table?")
  expect(screen.getAllByText("Твой ответ: krzesło")).toHaveLength(1)
})

test("a definitive validation error unlocks text so a corrected answer gets a new key", async () => {
  const posts: Record<string, unknown>[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/study/5")
        return new Response(
          JSON.stringify({
            id: 5,
            topic_ids: [1],
            topic_names: ["Polski"],
            mode: "quiz",
            position: 0,
            count: 1,
            answered: 0,
            status: "active",
            card: card("written", { case_sensitive: false }),
          }),
          { headers: { "Content-Type": "application/json" } }
        )
      if (path.endsWith("/answer")) {
        posts.push(JSON.parse(String(init?.body)))
        return posts.length === 1
          ? new Response(JSON.stringify({ detail: "Проверь ответ" }), {
              status: 422,
              headers: { "Content-Type": "application/json" },
            })
          : new Response(
              JSON.stringify({
                correct: true,
                card: { ...card("written", null), answer: "Nil" },
              }),
              { headers: { "Content-Type": "application/json" } }
            )
      }
      return new Response("[]", {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  render(<Study id={5} />)
  const input = await screen.findByRole("textbox", { name: "Твой ответ" })
  await userEvent.type(input, "bad")
  await userEvent.click(screen.getByRole("button", { name: "Проверить ответ" }))
  await screen.findByText("Проверь ответ")
  expect(input).toBeEnabled()
  await userEvent.clear(input)
  await userEvent.type(input, "Nil{Enter}")
  await screen.findByText("Верно!")
  expect(posts[1].text).toBe("Nil")
  expect(posts[1].idempotency_key).not.toBe(posts[0].idempotency_key)
})
