import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import EditQuestion from "../src/features/exercises/EditQuestion"
import RegenerateQuestion from "../src/features/exercises/RegenerateQuestion"
import type { Card } from "../src/types"

const image = {
  asset_id: "old",
  url: "/api/cards/1/images/question",
  alt: "Old river",
  width: 10,
  height: 10,
  mime: "image/webp",
  origin: "upload",
}
const card = {
  id: 1,
  topic_id: 1,
  question: "Rzeka?",
  answer: "Nil",
  mode: "flashcard",
  options: [],
  correct_indices: [],
  version: 2,
  status: "saved",
  sources: [],
  images: { question: image },
  question_type: "choice",
  exercise: null,
  language: "pl",
} as Card
const draft = {
  ...image,
  asset_id: "new",
  id: "new",
  url: "/api/image-candidates/new/preview",
  alt: "",
  slot: "question",
  stage: "draft",
  can_apply: true,
  target_version: 2,
}
beforeEach(() => localStorage.setItem("learning-ui-language", "en"))
function server(items: unknown[] = []) {
  const calls: { path: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const body =
        init?.body instanceof FormData
          ? init.body
          : init?.body
            ? JSON.parse(String(init.body))
            : null
      calls.push({ path, method: init?.method || "GET", body })
      const data = path.endsWith("/image-candidates")
        ? init?.method === "POST"
          ? draft
          : { items, next_cursor: null }
        : path.endsWith("/rebase")
          ? draft
          : path.endsWith("/regenerate") || path === "/api/jobs/9"
            ? {
                id: 9,
                status: "succeeded",
                result: {
                  base_version: 2,
                  candidate: {
                    ...card,
                    images: undefined,
                    id: undefined,
                    version: undefined,
                    status: undefined,
                  },
                },
              }
            : {}
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      })
    })
  )
  return calls
}
async function edit() {
  await userEvent.click(screen.getByRole("button", { name: "Edit card" }))
}

test("upload previews privately, cancellation restores current image, and Save atomically includes text and alt", async () => {
  const calls = server()
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.upload(
    within(slot).getByLabelText("Upload image"),
    new File(["png"], "river.png", { type: "image/png" })
  )
  await waitFor(() =>
    expect(slot.querySelector("img")).toHaveAttribute("src", draft.url)
  )
  expect(calls.find((c) => c.method === "POST")?.body).toBeInstanceOf(FormData)
  expect(
    (calls.find((c) => c.method === "POST")?.body as FormData).get("version")
  ).toBe("2")
  await userEvent.click(
    within(slot).getByRole("button", { name: "Keep current image" })
  )
  expect(slot.querySelector("img")).toHaveAttribute("src", image.url)
  await userEvent.click(within(slot).getByRole("button", { name: "Use draft" }))
  await userEvent.clear(within(slot).getByLabelText("Image description"))
  await userEvent.type(
    within(slot).getByLabelText("Image description"),
    "Nil w Egipcie"
  )
  await userEvent.clear(screen.getByLabelText("Question", { exact: true }))
  await userEvent.type(
    screen.getByLabelText("Question", { exact: true }),
    "Jaka rzeka?"
  )
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({
      question: "Jaka rzeka?",
      version: 2,
      image_updates: { question: { asset_id: "new", alt: "Nil w Egipcie" } },
    })
  )
  expect(calls.filter((c) => c.method === "PATCH")).toHaveLength(1)
})

test("reopening restores drafts without claiming text or alt autosave, obsolete candidates require explicit free rebase", async () => {
  const calls = server([
    { ...draft, stage: "obsolete", can_apply: false, target_version: 1 },
  ])
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await screen.findByText("Question changed; review the image before rebasing.")
  expect(within(slot).getByRole("button", { name: "Use draft" })).toBeDisabled()
  await userEvent.click(
    within(slot).getByRole("button", {
      name: "Rebase to current version (free)",
    })
  )
  await waitFor(() =>
    expect(
      within(slot).getByRole("button", { name: "Use draft" })
    ).toBeEnabled()
  )
  expect(calls.find((c) => c.path.endsWith("/rebase"))?.body).toEqual({
    version: 2,
  })
  expect(calls.some((c) => c.path.includes("generate"))).toBe(false)
  expect(
    screen.getByText(
      "Uploaded drafts remain available. Text and descriptions are saved only when you save changes."
    )
  ).toBeVisible()
})

test("removal is explicit and can be cancelled without deleting the card image", async () => {
  const calls = server()
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.click(
    within(slot).getByRole("button", { name: "Remove image" })
  )
  expect(within(slot).queryByRole("img")).not.toBeInTheDocument()
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({
      image_updates: { question: { asset_id: null, alt: "" } },
    })
  )
  expect(calls.some((c) => c.method === "DELETE")).toBe(false)
})

test("regeneration keeps illustrations outside model inputs and strict candidate; remove applies atomically", async () => {
  const calls = server()
  render(<RegenerateQuestion card={card} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Regenerate question" })
  )
  await screen.findByText("Candidate")
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.click(
    within(slot).getByRole("button", { name: "Remove image" })
  )
  await userEvent.click(screen.getByRole("button", { name: "Apply variant" }))
  await waitFor(() =>
    expect(
      calls.find((c) => c.path.endsWith("/apply-regeneration"))?.body
    ).toMatchObject({
      image_updates: { question: { asset_id: null, alt: "" } },
    })
  )
  const request = calls.find((c) => c.path.endsWith("/regenerate"))
    ?.body as Record<string, unknown>
  expect(request).not.toHaveProperty("images")
  expect(request).not.toHaveProperty("image_updates")
  expect(
    (
      calls.find((c) => c.path.endsWith("/apply-regeneration"))?.body as Record<
        string,
        unknown
      >
    ).candidate
  ).not.toHaveProperty("images")
})

test("a slow gallery response cannot hide a new upload or enable Save while the upload is running", async () => {
  let finishGallery: (value: Response) => void = () => {}
  let finishUpload: (value: Response) => void = () => {}
  vi.stubGlobal(
    "fetch",
    vi.fn(
      (_path: string, init?: RequestInit) =>
        new Promise<Response>((resolve) => {
          if (init?.method === "POST") finishUpload = resolve
          else finishGallery = resolve
        })
    )
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.upload(
    within(slot).getByLabelText("Upload image"),
    new File(["png"], "river.png", { type: "image/png" })
  )
  expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled()
  finishUpload(new Response(JSON.stringify(draft)))
  await waitFor(() =>
    expect(slot.querySelector("img")).toHaveAttribute("src", draft.url)
  )
  finishGallery(new Response(JSON.stringify({ items: [], next_cursor: null })))
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Save changes" })).toBeEnabled()
  )
  expect(slot.querySelector("img")).toHaveAttribute("src", draft.url)
})

test.each([
  ["en", "Question image", "Answer image", "Edit card"],
  ["pl", "Obrazek pytania", "Obrazek odpowiedzi", "Edytuj pytanie"],
  ["ru", "Картинка вопроса", "Картинка ответа", "Изменить карточку"],
])(
  "%s editor localizes both image slots while retaining source language",
  async (locale, questionLabel, answerLabel, editLabel) => {
    localStorage.setItem("learning-ui-language", locale)
    server()
    render(<EditQuestion card={card} onSaved={() => {}} />)
    await userEvent.click(screen.getByRole("button", { name: editLabel }))
    expect(screen.getByRole("group", { name: questionLabel })).toBeVisible()
    expect(screen.getByRole("group", { name: answerLabel })).toBeVisible()
    expect(screen.getByDisplayValue("Rzeka?")).toBeVisible()
    expect(
      screen.queryByRole("button", { name: /paid|платно|płatnie/i })
    ).not.toBeInTheDocument()
  }
)

test("editing only alt keeps the existing asset, and cancelled text/alt reset on reopen", async () => {
  const calls = server()
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.clear(within(slot).getByLabelText("Image description"))
  await userEvent.type(
    within(slot).getByLabelText("Image description"),
    "Unsaved description"
  )
  await userEvent.clear(screen.getByLabelText("Question", { exact: true }))
  await userEvent.type(
    screen.getByLabelText("Question", { exact: true }),
    "Unsaved question"
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Cancel", exact: true })
  )
  await edit()
  expect(screen.getByLabelText("Question", { exact: true })).toHaveValue(
    "Rzeka?"
  )
  const description = within(
    screen.getByRole("group", { name: "Question image" })
  ).getByLabelText("Image description")
  expect(description).toHaveValue("Old river")
  await userEvent.clear(description)
  await userEvent.type(description, "Changed description")
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }))
  await waitFor(() =>
    expect(calls.find((c) => c.method === "PATCH")?.body).toMatchObject({
      image_updates: {
        question: { asset_id: "old", alt: "Changed description" },
      },
    })
  )
})

test("gallery pagination exposes older drafts and explicit discard restores the current image", async () => {
  const requests: string[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      requests.push(`${init?.method || "GET"} ${path}`)
      return new Response(
        JSON.stringify(
          path.endsWith("?cursor=50")
            ? { items: [draft], next_cursor: null }
            : init?.method === "DELETE"
              ? { discarded: true }
              : { items: [], next_cursor: 50 }
        )
      )
    })
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  await userEvent.click(
    await screen.findByRole("button", { name: "Load more drafts" })
  )
  await userEvent.click(
    await screen.findByRole("button", { name: "Use draft" })
  )
  expect(
    screen.getByRole("group", { name: "Question image" }).querySelector("img")
  ).toHaveAttribute("src", draft.url)
  await userEvent.click(screen.getByRole("button", { name: "Discard draft" }))
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Use draft" })
    ).not.toBeInTheDocument()
  )
  expect(
    screen.getByRole("group", { name: "Question image" }).querySelector("img")
  ).toHaveAttribute("src", image.url)
  expect(requests).toContain("GET /api/cards/1/image-candidates?cursor=50")
  expect(requests).toContain("DELETE /api/image-candidates/new")
})

test("network-failed regeneration freezes text and image choices for a safe identical retry", async () => {
  const calls = server()
  const fetch = globalThis.fetch
  let attempts = 0
  const applied: unknown[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path.endsWith("/apply-regeneration")) {
        applied.push(JSON.parse(String(init?.body)))
        if (++attempts === 1) throw new TypeError("offline")
      }
      return fetch(path, init)
    })
  )
  render(<RegenerateQuestion card={card} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Regenerate question" })
  )
  await screen.findByText("Candidate")
  await userEvent.click(
    within(screen.getByRole("group", { name: "Question image" })).getByRole(
      "button",
      { name: "Remove image" }
    )
  )
  await userEvent.click(screen.getByRole("button", { name: "Apply variant" }))
  await screen.findByRole("alert")
  expect(screen.getByRole("button", { name: "Edit card" })).toBeDisabled()
  expect(
    screen.getByRole("button", { name: "Keep current image" })
  ).toBeDisabled()
  await userEvent.click(screen.getByRole("button", { name: "Apply variant" }))
  await waitFor(() => expect(applied).toHaveLength(2))
  expect(applied[1]).toEqual(applied[0])
  expect(calls.filter((c) => c.path.endsWith("/regenerate"))).toHaveLength(1)
})

test("gallery pages deduplicate candidates when a concurrent upload shifts the numeric cursor", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (path: string) =>
        new Response(
          JSON.stringify(
            path.includes("?cursor=")
              ? {
                  items: [
                    draft,
                    {
                      ...draft,
                      id: "older",
                      asset_id: "older",
                      url: "/api/image-candidates/older/preview",
                    },
                  ],
                  next_cursor: null,
                }
              : { items: [draft], next_cursor: 50 }
          )
        )
    )
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  await userEvent.click(
    await screen.findByRole("button", { name: "Load more drafts" })
  )
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Use draft" })).toHaveLength(2)
  )
})

test("discarding a displayed draft from the first 50 does not skip the unseen 51st candidate", async () => {
  let remaining = Array.from({ length: 51 }, (_, index) => ({
    ...draft,
    id: `draft-${index}`,
    asset_id: `draft-${index}`,
    url: `/api/image-candidates/draft-${index}/preview`,
  }))
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        const id = path.split("/").pop()
        remaining = remaining.filter((item) => item.id !== id)
        return new Response(JSON.stringify({ discarded: true }))
      }
      const cursor = Number(
        new URL(path, "http://localhost").searchParams.get("cursor") || 0
      )
      return new Response(
        JSON.stringify({
          items: remaining.slice(cursor, cursor + 50),
          next_cursor: remaining.length > cursor + 50 ? cursor + 50 : null,
        })
      )
    })
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Use draft" })).toHaveLength(
      50
    )
  )
  await userEvent.click(
    screen.getAllByRole("button", { name: "Discard draft" })[0]
  )
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Use draft" })).toHaveLength(
      49
    )
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Load more drafts" })
  )
  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Use draft" })).toHaveLength(
      50
    )
  )
  expect(
    document.querySelector('a[href="/api/image-candidates/draft-50/preview"]')
  ).toBeInTheDocument()
  expect(
    document.querySelector('a[href="/api/image-candidates/draft-0/preview"]')
  ).not.toBeInTheDocument()
})
