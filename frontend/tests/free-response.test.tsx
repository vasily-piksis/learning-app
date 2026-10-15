import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import Study from "../src/features/Study"
import Generation from "../src/features/Generation"
import StartStudy from "../src/features/StartStudy"
import EditQuestion from "../src/features/exercises/EditQuestion"
import type { Card, StudySession, Topic } from "../src/types"

const exercise = {
  goal: "language" as const,
  language: "lt",
  level: "A1" as const,
  min_words: 100,
  max_words: 150,
  model_answer: "Ąžuolas auga miške.",
  rubric: [{ id: "r", label: "Aiškumas A1", weight: 100 }],
  expected_points: [
    {
      id: "p",
      text: "Medis",
      essential: true,
      sources: [{ document_id: 1, page: 1 }],
    },
  ],
  source_fragments: [
    { source: { document_id: 1, page: 1 }, text: "Ąžuolas auga miške." },
  ],
}
const card: Card = {
  id: 1,
  topic_id: 1,
  question: "Aprašyk medį",
  question_type: "free_response",
  exercise,
  mode: "quiz",
  options: [],
  version: 1,
  status: "saved",
  sources: [],
}
const session: StudySession = {
  id: 8,
  topic_ids: [1],
  topic_names: ["Lietuvių"],
  mode: "quiz",
  position: 0,
  status: "active",
  count: 1,
  answered: 0,
  correct: 0,
  card: {
    ...card,
    exercise: {
      goal: "language",
      language: "lt",
      level: "A1",
      min_words: 100,
      max_words: 150,
    },
  },
}
const pending = {
  evaluation_id: 9,
  job_id: 10,
  status: "queued",
  submission: { free_text: "Ąžuolas", audio_answer_id: null },
  error: null,
  error_code: null,
}
const feedback = {
  session_id: 8,
  position: 0,
  next_position: 1,
  card,
  submission: { free_text: "Ąžuolas" },
  evaluation_id: 9,
  correct: false,
  score: 75,
  word_count: 1,
  word_count_version: 1,
  word_limit: { min: 100, max: 150, met: false },
  language_match: true,
  rubric_scores: [{ criterion_id: "r", score: 3, explanation: "Aišku" }],
  point_checks: [{ point_id: "p", met: true, evidence: [] }],
  corrections: [],
  summary: "Geras atsakymas",
  suggestions: ["Rašyk daugiau"],
  input_method: "text",
}
function server(answer: unknown = pending, state: unknown = null) {
  const requests: { path: string; body: Record<string, unknown> }[] = []
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const path = String(url).replace("/api", "")
    if (init?.method === "POST") {
      requests.push({ path, body: JSON.parse(String(init.body)) })
      return new Response(JSON.stringify(answer), { status: 202 })
    }
    return new Response(
      JSON.stringify(
        path.includes("evaluations")
          ? state
          : path === "/study/8"
            ? session
            : []
      )
    )
  })
  vi.stubGlobal("fetch", fetcher)
  return requests
}
beforeEach(() => {
  localStorage.setItem("learning-ui-language", "en")
  sessionStorage.clear()
})
test("local scalar and word counters warn below and above 100–150 without blocking paid submission or calling AI while typing", async () => {
  const requests = server()
  render(<Study id={8} />)
  const input = await screen.findByLabelText("Your written response")
  fireEvent.change(input, { target: { value: "Ąžuolas" } })
  expect(screen.getByText("Words: 1 · target 100–150")).toBeVisible()
  expect(screen.getByText(/Outside the suggested word range/)).toBeVisible()
  expect(
    screen.getByRole("button", { name: "Grade with AI (paid)" })
  ).toBeEnabled()
  fireEvent.change(input, { target: { value: "žodis ".repeat(151) } })
  expect(screen.getByText("Words: 151 · target 100–150")).toBeVisible()
  expect(requests).toHaveLength(0)
  expect(input).not.toHaveAttribute("maxlength")
  fireEvent.change(input, { target: { value: "𐐀".repeat(10000) } })
  expect(
    screen.getByRole("button", { name: "Grade with AI (paid)" })
  ).toBeEnabled()
  fireEvent.change(input, { target: { value: "𐐀".repeat(10001) } })
  expect(
    screen.getByRole("button", { name: "Grade with AI (paid)" })
  ).toBeDisabled()
})
test.each([
  { detail: "unreadable success" },
  { evaluation_id: 9, status: "completed" },
])(
  "uncertain success freezes original text and replays identical key and body: %j",
  async (malformed) => {
    const requests = server(malformed)
    render(<Study id={8} />)
    const input = await screen.findByLabelText("Your written response")
    fireEvent.change(input, { target: { value: "Ąžuolas" } })
    await userEvent.click(
      screen.getByRole("button", { name: "Grade with AI (paid)" })
    )
    expect(input).toBeDisabled()
    await userEvent.click(
      await screen.findByRole("button", { name: "Check submission again" })
    )
    expect(requests).toHaveLength(2)
    expect(requests[0].body).toEqual(requests[1].body)
  }
)
test("reload recovers authoritative pending submission without sending another paid request", async () => {
  const requests = server(pending, pending)
  render(<Study id={8} />)
  await waitFor(() =>
    expect(screen.getByLabelText("Your written response")).toHaveValue(
      "Ąžuolas"
    )
  )
  await waitFor(() =>
    expect(screen.getByLabelText("Your written response")).toBeDisabled()
  )
  expect(screen.getByText("Grading in progress")).toBeVisible()
  expect(requests).toHaveLength(0)
  expect(screen.queryByText("Aiškumas A1")).not.toBeInTheDocument()
})
test("failed grading is neutral and explicit same-answer retry requires a new cost acknowledgement", async () => {
  const requests = server(pending, {
    ...pending,
    status: "unknown",
    error_code: "unknown",
  })
  render(<Study id={8} />)
  const retry = await screen.findByRole("button", {
    name: "Retry the same answer (paid)",
  })
  expect(retry).toBeDisabled()
  expect(screen.queryByText(/Incorrect/)).not.toBeInTheDocument()
  await userEvent.click(
    screen.getByRole("checkbox", { name: /I understand another request/ })
  )
  await userEvent.click(retry)
  expect(requests[0].path).toBe("/evaluations/9/retry")
  expect(requests[0].body.acknowledge_extra_cost).toBe(true)
})
test("completed feedback separates score, rubric and word limit without translating Lithuanian content", async () => {
  server(feedback)
  render(<Study id={8} />)
  fireEvent.change(await screen.findByLabelText("Your written response"), {
    target: { value: "Ąžuolas" },
  })
  await userEvent.click(
    screen.getByRole("button", { name: "Grade with AI (paid)" })
  )
  expect(await screen.findByText("Score: 75/100")).toBeVisible()
  expect(screen.getByText("Aiškumas A1: 3/4")).toBeVisible()
  expect(screen.getByText("Geras atsakymas")).toBeVisible()
  expect(screen.getByText("Word target not met")).toBeVisible()
})
test("private criteria and model answer are editable in the editor", async () => {
  server()
  render(<EditQuestion card={card} onSaved={() => {}} showImages={false} />)
  await userEvent.click(screen.getByRole("button", { name: "Edit card" }))
  expect(await screen.findByLabelText("Model answer")).toHaveValue(
    exercise.model_answer
  )
  expect(screen.getByLabelText("Criterion 1")).toHaveValue("Aiškumas A1")
})
test("free response settings require explicit source language and CEFR, with optional word bounds", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            String(url).includes("documents")
              ? [{ id: 1, status: "ready", name: "LT", language: null }]
              : []
          )
        )
    )
  )
  render(<Generation initialTopics={[1]} initialMethod="free_response" />)
  const language = await screen.findByLabelText("Original language code")
  expect(language).toHaveValue("")
  expect(
    screen.getByRole("button", { name: "Create questions" })
  ).toBeDisabled()
  fireEvent.change(language, { target: { value: "lt" } })
  await userEvent.click(
    screen.getByRole("radio", { name: "Language and grammar" })
  )
  expect(
    screen.getByRole("button", { name: "Create questions" })
  ).toBeDisabled()
})
test("unavailable evaluation retains saved readiness and mixed practice excludes paid work by default", async () => {
  const topic = {
    id: 1,
    name: "LT",
    subject_id: 1,
    version: 1,
    card_count: 1,
    document_count: 1,
    practice_availability: {
      free_response: {
        ready_count: 3,
        draft_count: 0,
        needs_options_count: 0,
        preparation_job_id: null,
        preparation_status: null,
        has_ready_materials: true,
        last_outcome: null,
        runtime_unavailable: true,
      },
    },
  } as Topic
  server()
  render(<StartStudy topicIds={[1]} topics={[topic]} />)
  await userEvent.click(
    screen.getByRole("combobox", { name: "Practice method" })
  )
  await userEvent.click(
    screen.getByRole("option", { name: "Free response · 3" })
  )
  expect(screen.getByText(/Ready: 3/)).toBeVisible()
  expect(
    screen.getByText(
      "AI grading is currently unavailable. Saved exercises remain available."
    )
  ).toBeVisible()
  expect(screen.getByRole("button", { name: "Start studying" })).toBeDisabled()
})

test.each([
  ["quota_exceeded", "Daily grading limit reached"],
  [
    "runtime_unavailable",
    "AI grading is currently unavailable. Saved exercises remain available.",
  ],
  ["failed", "Grading did not finish. No score was assigned."],
])(
  "%s is a neutral state with immutable text and no score",
  async (error_code, message) => {
    const requests = server(pending, {
      ...pending,
      status: "failed",
      error_code,
    })
    render(<Study id={8} />)
    expect(await screen.findByText(message)).toBeVisible()
    expect(screen.getByLabelText("Your written response")).toBeDisabled()
    expect(screen.queryByText(/Score:/)).not.toBeInTheDocument()
    expect(requests).toHaveLength(0)
  }
)
test("a timeout keeps the original key through remount and manual replay", async () => {
  const requests: unknown[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        requests.push(JSON.parse(String(init.body)))
        throw new Error("timeout")
      }
      return new Response(
        JSON.stringify(String(url).includes("evaluations") ? null : session)
      )
    })
  )
  const view = render(<Study id={8} />)
  const input = await screen.findByLabelText("Your written response")
  await waitFor(() => expect(input).toBeEnabled())
  fireEvent.change(input, { target: { value: "Ąžuolas" } })
  await userEvent.click(
    screen.getByRole("button", { name: "Grade with AI (paid)" })
  )
  await screen.findByRole("button", { name: "Check submission again" })
  view.unmount()
  render(<Study id={8} />)
  await userEvent.click(
    await screen.findByRole("button", { name: "Check submission again" })
  )
  expect(requests).toHaveLength(2)
  expect(requests[0]).toEqual(requests[1])
})

test("malformed completed feedback cannot release a paid key even when scalar fields look valid", async () => {
  const { isEvaluationFeedback } =
    await import("../src/features/exercises/FreeResponse")
  expect(
    isEvaluationFeedback({
      ...feedback,
      card: { ...card, exercise: { rubric: null, expected_points: [] } },
    })
  ).toBe(false)
  expect(
    isEvaluationFeedback({
      ...feedback,
      point_checks: [{ point_id: "p", met: true, evidence: [{}] }],
    })
  ).toBe(false)
})

test.each([
  { reason: "word target", grade: feedback },
  {
    reason: "essential point",
    grade: {
      ...feedback,
      word_limit: { min: null, max: null, met: true },
      point_checks: [{ point_id: "p", met: false, evidence: [] }],
    },
  },
  {
    reason: "language mismatch",
    grade: {
      ...feedback,
      word_limit: { min: null, max: null, met: true },
      language_match: false,
    },
  },
])(
  "a completed assessment failing $reason clearly says not completed while retaining its content score",
  async ({ grade }) => {
    server(grade)
    render(<Study id={8} />)
    const input = await screen.findByLabelText("Your written response")
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, { target: { value: "Ąžuolas" } })
    await userEvent.click(
      screen.getByRole("button", { name: "Grade with AI (paid)" })
    )
    expect(
      await screen.findByText("Assignment not completed yet")
    ).toBeVisible()
    expect(screen.getByText("Score: 75/100")).toBeVisible()
    expect(
      screen.queryByText("Grading did not finish. No score was assigned.")
    ).not.toBeInTheDocument()
  }
)
test("an assignment meeting the criteria has an explicit completed status", async () => {
  server({
    ...feedback,
    correct: true,
    word_limit: { min: null, max: null, met: true },
  })
  render(<Study id={8} />)
  const input = await screen.findByLabelText("Your written response")
  await waitFor(() => expect(input).toBeEnabled())
  fireEvent.change(input, { target: { value: "Ąžuolas" } })
  await userEvent.click(
    screen.getByRole("button", { name: "Grade with AI (paid)" })
  )
  expect(await screen.findByText("Assignment completed")).toBeVisible()
})

test.each([
  ["null source", { ...feedback, card: { ...card, sources: [null] } }],
  [
    "source name",
    {
      ...feedback,
      card: { ...card, sources: [{ document_id: 1, page: 1, name: {} }] },
    },
  ],
  [
    "source URL",
    {
      ...feedback,
      card: { ...card, sources: [{ document_id: 1, page: 1, url: [] }] },
    },
  ],
  [
    "source timestamp",
    {
      ...feedback,
      card: {
        ...card,
        sources: [{ document_id: 1, page: 1, start_seconds: [] }],
      },
    },
  ],
  [
    "answer object",
    { ...feedback, card: { ...card, answer: { text: "Medis" } } },
  ],
  [
    "answer image",
    {
      ...feedback,
      card: { ...card, images: { answer: { url: "/image", alt: {} } } },
    },
  ],
  [
    "question image",
    { ...feedback, card: { ...card, images: { question: "invalid" } } },
  ],
  ["array status", { evaluation_id: 9, job_id: 10, status: ["queued"] }],
])(
  "malformed %s preserves the paid request across reload and identical manual replay",
  async (_, response) => {
    const requests = server(response)
    const view = render(<Study id={8} />)
    const input = await screen.findByLabelText("Your written response")
    await waitFor(() => expect(input).toBeEnabled())
    fireEvent.change(input, { target: { value: "Ąžuolas" } })
    await userEvent.click(
      screen.getByRole("button", { name: "Grade with AI (paid)" })
    )
    await screen.findByRole("button", { name: "Check submission again" })
    const frozen = sessionStorage.getItem("free-response-v1:8:0")
    expect(frozen).not.toBeNull()
    expect(screen.getByLabelText("Your written response")).toHaveValue(
      "Ąžuolas"
    )
    expect(screen.getByLabelText("Your written response")).toBeDisabled()
    expect(screen.queryByText("Score: 75/100")).not.toBeInTheDocument()
    view.unmount()
    render(<Study id={8} />)
    await userEvent.click(
      await screen.findByRole("button", { name: "Check submission again" })
    )
    expect(requests).toHaveLength(2)
    expect(requests[1]).toEqual(requests[0])
    expect(sessionStorage.getItem("free-response-v1:8:0")).toBe(frozen)
  }
)

test("completed feedback preserves valid optional legacy sources and private image metadata", async () => {
  const { isEvaluationFeedback } =
    await import("../src/features/exercises/FreeResponse")
  expect(isEvaluationFeedback(feedback)).toBe(true)
  expect(
    isEvaluationFeedback({
      ...feedback,
      card: {
        ...card,
        answer: "Medis",
        sources: [
          { document_id: 1, page: 1 },
          {
            document_id: 2,
            page: 3,
            available: false,
            name: "Deleted material",
          },
          {
            document_id: 3,
            page: 1,
            url: "https://www.youtube.com/watch?v=LTfree12345&t=5",
            name: "LT",
            start_seconds: 5.5,
            end_seconds: null,
          },
        ],
        images: {
          answer: {
            asset_id: "asset",
            url: "/api/private-image",
            alt: "Ąžuolas",
            width: 100,
            height: 100,
            mime: "image/png",
            origin: "upload",
          },
        },
      },
    })
  ).toBe(true)
})
