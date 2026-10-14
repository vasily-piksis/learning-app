import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import Generation from "../src/features/Generation"
import { EditCard } from "../src/components/shared"
import type { Card } from "../src/types"

beforeEach(() => localStorage.setItem("learning-ui-language", "ru"))
function generationServer() {
  const submissions: Record<string, unknown>[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      let data: unknown
      if (path === "/api/topics")
        data = [
          {
            id: 1,
            subject_id: 1,
            name: "Topic",
            version: 1,
            card_count: 0,
            document_count: 1,
          },
        ]
      else if (path === "/api/topics/1/documents")
        data = [
          {
            id: 1,
            topic_id: 1,
            name: "lesson.pdf",
            status: "ready",
            used_for_questions: false,
          },
        ]
      else if (path === "/api/generate") {
        submissions.push(JSON.parse(String(init?.body)))
        data = {
          id: 8,
          kind: "generate",
          status: "queued",
          error: null,
          result: null,
          created: "2026-10-14",
          topic_ids: [1],
        }
      } else throw new Error(`Unexpected API ${path}`)
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  return submissions
}

test("generation selects exercise types and sends one total count without translation", async () => {
  const submissions = generationServer()
  render(<Generation initialTopics={[1]} />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Письменный ответ", exact: true })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Выбор ответа", exact: true })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Создать вопросы", exact: true })
  )
  await waitFor(() => expect(submissions).toHaveLength(1))
  expect(submissions[0]).toMatchObject({
    question_types: ["written"],
    practice_goal: "content",
    count: 10,
    mode: "quiz",
    topic_ids: [1],
  })
  expect(submissions[0]).not.toHaveProperty("target_language")
  expect(submissions[0].idempotency_key).toEqual(expect.any(String))
})

test("changing practice goal removes incompatible selections without calling the model", async () => {
  const submissions = generationServer()
  render(<Generation initialTopics={[1]} />)
  await userEvent.click(
    await screen.findByRole("radio", {
      name: "Язык и грамматику",
      exact: true,
    })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Окончания", exact: true })
  )
  await userEvent.click(
    screen.getByRole("radio", { name: "Содержание темы", exact: true })
  )
  expect(
    screen.queryByRole("button", { name: "Окончания", exact: true })
  ).not.toBeInTheDocument()
  expect(
    await screen.findByText(
      "Окончания и сборка предложения доступны для языковой практики."
    )
  ).toBeVisible()
  expect(submissions).toHaveLength(0)
})

test("written exercise editor submits accepted answers and version rather than an independent solution", async () => {
  let submitted: Record<string, unknown> | undefined
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      submitted = JSON.parse(String(init?.body))
      return new Response(JSON.stringify({}), {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  const card = {
    id: 1,
    topic_id: 1,
    question: "Как называется гражданин?",
    answer: "pilietis",
    question_type: "written",
    exercise: { accepted_answers: ["pilietis"], case_sensitive: false },
    mode: "quiz",
    options: [],
    version: 3,
    status: "saved",
    sources: [],
  } as unknown as Card
  render(<EditCard card={card} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Изменить карточку" })
  )
  const input = await screen.findByLabelText("Допустимые ответы")
  await userEvent.clear(input)
  await userEvent.type(input, "pilietis\ngyventojas")
  await userEvent.click(
    screen.getByRole("button", { name: "Сохранить изменения" })
  )
  await waitFor(() => expect(submitted).toBeDefined())
  expect(submitted).toMatchObject({
    exercise: {
      accepted_answers: ["pilietis", "gyventojas"],
      case_sensitive: false,
    },
    version: 3,
  })
  expect(submitted).not.toHaveProperty("answer")
})

test.each([
  [
    "gap",
    {
      segments: [{ text: "I " }, { gap_id: "verb" }],
      gaps: [{ id: "verb", accepted_answers: ["am"] }],
      case_sensitive: false,
      accepted_combinations: [["am"]],
    },
    "Сочетание 1, пропуск 1",
    "was",
    "accepted_combinations",
    [["was"]],
  ],
  [
    "ending",
    {
      segments: [{ text: "Su draug" }, { gap_id: "ending" }],
      gaps: [{ id: "ending", accepted_answers: ["u"] }],
      case_sensitive: false,
      accepted_combinations: [["u"]],
    },
    "Сочетание 1, пропуск 1",
    "ais",
    "accepted_combinations",
    [["ais"]],
  ],
  [
    "matching",
    {
      pairs: [
        { left: "a", right: "1" },
        { left: "b", right: "2" },
      ],
    },
    "Слева 1",
    "c",
    "pairs",
    [
      { left: "c", right: "1" },
      { left: "b", right: "2" },
    ],
  ],
  [
    "ordering",
    {
      tokens: ["ich", "komme", "morgen"],
      accepted_orders: [["ich", "komme", "morgen"]],
    },
    "Допустимый порядок 1",
    "morgen\nkomme\nich",
    "accepted_orders",
    [["morgen", "komme", "ich"]],
  ],
])(
  "%s editor updates the structured criteria",
  async (kind, exercise, label, inputValue, field, expected) => {
    let submitted: Record<string, unknown> | undefined
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_path: string, init?: RequestInit) => {
        submitted = JSON.parse(String(init?.body))
        return new Response("{}", {
          headers: { "Content-Type": "application/json" },
        })
      })
    )
    const card = {
      id: 1,
      topic_id: 1,
      question: "Question",
      answer: "Original solution",
      question_type: kind,
      exercise,
      mode: "quiz",
      options: [],
      version: 4,
      status: "saved",
      sources: [],
    } as unknown as Card
    render(<EditCard card={card} onSaved={() => {}} />)
    await userEvent.click(
      screen.getByRole("button", { name: "Изменить карточку" })
    )
    const input = await screen.findByLabelText(String(label))
    await userEvent.clear(input)
    await userEvent.type(input, String(inputValue))
    await userEvent.click(
      screen.getByRole("button", { name: "Сохранить изменения" })
    )
    await waitFor(() => expect(submitted).toBeDefined())
    expect(submitted).toMatchObject({
      version: 4,
      exercise: { [String(field)]: expected },
    })
    expect(submitted).not.toHaveProperty("answer")
    if (kind === "gap" || kind === "ending")
      expect(submitted).toMatchObject({
        exercise: {
          gaps: [
            {
              id: kind === "gap" ? "verb" : "ending",
              accepted_answers: [inputValue],
            },
          ],
        },
      })
  }
)

test("generation refuses a total count smaller than selected types", async () => {
  const requests = generationServer()
  render(<Generation initialTopics={[1]} />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Письменный ответ", exact: true })
  )
  const count = screen.getByLabelText("Сколько вопросов?")
  await userEvent.clear(count)
  await userEvent.type(count, "1")
  expect(
    screen.getByRole("button", { name: "Создать вопросы", exact: true })
  ).toBeDisabled()
  expect(requests).toHaveLength(0)
})

test("a failed exercise edit retains the entered answer for correction", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({ detail: "Проверьте параметры задания" }),
          { status: 422, headers: { "Content-Type": "application/json" } }
        )
    )
  )
  const card = {
    id: 1,
    topic_id: 1,
    question: "Word",
    answer: "stalas",
    question_type: "written",
    exercise: { accepted_answers: ["stalas"], case_sensitive: false },
    mode: "quiz",
    options: [],
    version: 1,
    status: "saved",
    sources: [],
  } as unknown as Card
  render(<EditCard card={card} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Изменить карточку" })
  )
  const input = await screen.findByLabelText("Допустимые ответы")
  await userEvent.clear(input)
  await userEvent.type(input, "lentelė")
  await userEvent.click(
    screen.getByRole("button", { name: "Сохранить изменения" })
  )
  expect(await screen.findByText("Проверьте параметры задания")).toBeVisible()
  expect(input).toHaveValue("lentelė")
})

test("removing a gap also removes its combination column", async () => {
  let submitted: Record<string, unknown> | undefined
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_path: string, init?: RequestInit) => {
      submitted = JSON.parse(String(init?.body))
      return new Response("{}", {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  const card = {
    id: 1,
    topic_id: 1,
    question: "Complete",
    answer: "I am",
    question_type: "gap",
    exercise: {
      segments: [{ gap_id: "subject" }, { text: " " }, { gap_id: "verb" }],
      gaps: [
        { id: "subject", accepted_answers: ["I", "We"] },
        { id: "verb", accepted_answers: ["am", "are"] },
      ],
      case_sensitive: false,
      accepted_combinations: [
        ["I", "am"],
        ["We", "are"],
      ],
    },
    mode: "quiz",
    options: [],
    version: 1,
    status: "saved",
    sources: [],
  } as unknown as Card
  render(<EditCard card={card} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Изменить карточку" })
  )
  await userEvent.click(
    await screen.findByRole("button", { name: "Убрать пропуск 2" })
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Сохранить изменения" })
  )
  await waitFor(() => expect(submitted).toBeDefined())
  expect(submitted).toMatchObject({
    exercise: {
      gaps: [{ id: "subject", accepted_answers: ["I", "We"] }],
      accepted_combinations: [["I"], ["We"]],
      segments: [{ gap_id: "subject" }, { text: " " }],
    },
  })
})

test.each(["written", "flashcard"])(
  "preset %s generates exactly that method",
  async (method) => {
    const submissions = generationServer()
    render(<Generation initialTopics={[1]} initialMethod={method} />)
    await userEvent.click(
      await screen.findByRole("button", {
        name: "Создать вопросы",
        exact: true,
      })
    )
    await waitFor(() => expect(submissions).toHaveLength(1))
    expect(submissions[0]).toMatchObject({
      topic_ids: [1],
      mode: method === "flashcard" ? "flashcard" : "quiz",
      question_types: [method === "flashcard" ? "choice" : method],
    })
  }
)

test.each([true, false])(
  "unsupported type reason is visible with partial=%s",
  async (partial) => {
    const { default: Drafts } = await import("../src/features/Drafts")
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify(
              partial
                ? [
                    {
                      id: 1,
                      topic_id: 1,
                      question: "When?",
                      answer: "1989",
                      mode: "quiz",
                      question_type: "written",
                      exercise: {
                        accepted_answers: ["1989"],
                        case_sensitive: false,
                      },
                      options: [],
                      sources: [],
                      status: "draft",
                      version: 1,
                    },
                  ]
                : []
            ),
            { headers: { "Content-Type": "application/json" } }
          )
      )
    )
    render(
      <Drafts
        job={{
          id: 9,
          kind: "generate",
          status: "succeeded",
          error: null,
          created: "2026-10-14",
          topic_ids: [1],
          result: {
            warnings: ["Brak materiału do ćwiczenia końcówek."],
            unsupported_types: [
              {
                question_type: "ending",
                reason: "Brak materiału do ćwiczenia końcówek.",
              },
            ],
          },
        }}
      />
    )
    expect(
      await screen.findByText("Brak materiału do ćwiczenia końcówek.")
    ).toBeVisible()
    if (partial)
      expect(await screen.findByText("Письменный ответ")).toBeVisible()
    else expect(await screen.findByText("Карточки не созданы")).toBeVisible()
  }
)

test("model warnings retain source language when the interface is Polish", async () => {
  const { default: Drafts } = await import("../src/features/Drafts")
  localStorage.setItem("learning-ui-language", "pl")
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response("[]", { headers: { "Content-Type": "application/json" } })
    )
  )
  render(
    <Drafts
      job={{
        id: 10,
        kind: "generate",
        status: "succeeded",
        error: null,
        created: "2026-10-14",
        topic_ids: [1],
        result: {
          warnings: ["Карточки не созданы"],
          model_warnings: ["Карточки не созданы"],
        },
      }}
    />
  )
  expect(await screen.findByText("Карточки не созданы")).toBeVisible()
})
