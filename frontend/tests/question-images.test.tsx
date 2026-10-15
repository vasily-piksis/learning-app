import { act, render, screen, waitFor, within } from "@testing-library/react"
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
      const data = path.startsWith("/api/jobs?")
        ? []
        : path === "/api/image-generation"
          ? { status: "disabled", remaining: 10, settings: {} }
          : path.endsWith("/image-candidates")
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
  expect(
    calls.some((c) => c.method === "POST" && c.path.includes("generate"))
  ).toBe(false)
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
      screen.getAllByRole("button", { name: /paid|платно|płatnie/i })[0]
    ).toBeDisabled()
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

const availability = {
  status: "ready",
  enabled: true,
  model: "gpt-image-1",
  settings: { n: 1, size: "1024x1024", quality: "low", output_format: "webp" },
  access_status: "unverified",
  limit: 10,
  used: 0,
  remaining: 10,
  timezone: "Europe/Vilnius",
  next_reset_at: "2026-10-14T21:00:00Z",
}
function paidServer(
  initial: Record<string, unknown>[] = [],
  config = availability
) {
  const calls: { path: string; body: unknown; method: string }[] = []
  let jobs = initial
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const body = init?.body ? JSON.parse(String(init.body)) : null
      calls.push({ path, body, method: init?.method || "GET" })
      let data: unknown = {}
      if (path === "/api/image-generation") data = config
      else if (path.startsWith("/api/jobs?")) data = jobs
      else if (path.endsWith("/image-candidates"))
        data = { items: [], next_cursor: null }
      else if (path.endsWith("/generate-image")) {
        jobs = [
          {
            id: 21,
            kind: "generate_image",
            card_id: 1,
            slot: "question",
            status: "queued",
            result: null,
          },
        ]
        data = jobs[0]
      } else if (path.endsWith("/retry-image-save"))
        data = {
          ...jobs[0],
          status: "succeeded",
          result: { candidate: { ...draft, origin: "generated" } },
        }
      else if (path.endsWith("/retry-image"))
        data = { ...jobs[0], status: "queued", result: null }
      else if (path.startsWith("/api/jobs/")) data = jobs[0]
      return new Response(JSON.stringify(data))
    })
  )
  return calls
}
test("paid generation is explicit, starts with editable no-text Polish prompt, and never runs on mount", async () => {
  const calls = paidServer()
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  const button = within(slot).getByRole("button", {
    name: "Generate image (paid)",
  })
  await waitFor(() => expect(button).toBeEnabled())
  expect(
    within(slot).getByLabelText("Image prompt").getAttribute("value") ||
      (within(slot).getByLabelText("Image prompt") as HTMLTextAreaElement).value
  ).toContain("bez tekstu")
  expect(screen.getByText(/A parent or user must review/)).toBeVisible()
  expect(screen.getByText(/1024x1024/)).toBeVisible()
  expect(calls.some((c) => c.method === "POST")).toBe(false)
  await userEvent.clear(within(slot).getByLabelText("Image prompt"))
  await userEvent.type(
    within(slot).getByLabelText("Image prompt"),
    "Moja ilustracja"
  )
  await userEvent.click(button)
  await waitFor(() => expect(button).toBeDisabled())
  expect(calls.find((c) => c.path.endsWith("/generate-image"))?.body).toEqual({
    version: 2,
    slot: "question",
    prompt: "Moja ilustracja",
    idempotency_key: expect.any(String),
  })
  expect(calls.filter((c) => c.method === "POST")).toHaveLength(1)
  expect(
    within(slot).getByText(
      "Image generation in progress. You can return later."
    )
  ).toBeVisible()
})
test("existing unknown image jobs recover without paid calls and require explicit additional-cost acknowledgement", async () => {
  const calls = paidServer([
    {
      id: 21,
      kind: "generate_image",
      card_id: 1,
      slot: "question",
      status: "unknown",
      result: null,
    },
  ])
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  const retry = await within(slot).findByRole("button", {
    name: "Try image generation again (paid)",
  })
  expect(retry).toBeDisabled()
  expect(within(slot).queryByLabelText("Image prompt")).not.toBeInTheDocument()
  expect(
    within(slot).getByText(
      "This job uses its original prompt and settings. Discard it first to use a new prompt."
    )
  ).toBeVisible()
  expect(
    within(slot).getByText(/The result and charge may be unknown/)
  ).toBeVisible()
  expect(calls.some((c) => c.method === "POST")).toBe(false)
  await userEvent.click(
    within(slot).getByLabelText("I understand another attempt may cost extra")
  )
  await userEvent.click(retry)
  expect(calls.find((c) => c.path.endsWith("/retry-image"))?.body).toEqual({
    idempotency_key: expect.any(String),
    acknowledge_extra_cost: true,
  })
  expect(calls.some((c) => /\/retry$/.test(c.path))).toBe(false)
})
test.each(["ready", "disabled"])(
  "durable image failures offer free local save with %s configuration and require candidate review",
  async (status) => {
    const calls = paidServer(
      [
        {
          id: 21,
          kind: "generate_image",
          card_id: 1,
          slot: "question",
          status: "failed",
          result: { can_retry_save: true },
        },
      ],
      { ...availability, status, enabled: status === "ready" }
    )
    render(<EditQuestion card={card} onSaved={() => {}} />)
    await edit()
    const slot = screen.getByRole("group", { name: "Question image" })
    await userEvent.click(
      await within(slot).findByRole("button", {
        name: "Retry saving image (free)",
      })
    )
    await within(slot).findByRole("button", { name: "Use draft" })
    expect(slot.querySelector("img")).toHaveAttribute("src", image.url)
    expect(calls.filter((c) => c.method === "POST").map((c) => c.path)).toEqual(
      ["/api/jobs/21/retry-image-save"]
    )
    await userEvent.click(
      within(slot).getByRole("button", { name: "Use draft" })
    )
    expect(slot.querySelector("img")).toHaveAttribute("src", draft.url)
    expect(within(slot).getByText("Created by AI")).toBeVisible()
  }
)
test("exhausted budget and invalid timezone safely disable paid controls while upload remains available", async () => {
  paidServer([], {
    ...availability,
    status: "invalid_timezone",
    remaining: 0,
    timezone: "bad/timezone",
    next_reset_at: null as unknown as string,
  })
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await screen.findByText(
    "Image generation is unavailable. Upload is available."
  )
  expect(
    within(slot).getByRole("button", { name: "Generate image (paid)" })
  ).toBeDisabled()
  expect(within(slot).getByLabelText("Upload image")).toBeEnabled()
})

test("discarding a generated job removes its candidate and restores current selection", async () => {
  paidServer([
    {
      id: 21,
      kind: "generate_image",
      card_id: 1,
      slot: "question",
      status: "failed",
      result: { can_retry_save: true },
    },
  ])
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.click(
    await within(slot).findByRole("button", {
      name: "Retry saving image (free)",
    })
  )
  await userEvent.click(
    await within(slot).findByRole("button", { name: "Use draft" })
  )
  await userEvent.click(
    within(slot).getByRole("button", { name: "Discard image generation" })
  )
  await waitFor(() =>
    expect(
      within(slot).queryByRole("button", { name: "Use draft" })
    ).not.toBeInTheDocument()
  )
  expect(slot.querySelector("img")).toHaveAttribute("src", image.url)
})

test.each([0, 500])(
  "lost or server-failed paid response %s freezes the identical request key without automatic attempts",
  async (status) => {
    const calls = paidServer()
    const fetch = globalThis.fetch
    const requests: unknown[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (path.endsWith("/generate-image")) {
          requests.push(JSON.parse(String(init?.body)))
          if (requests.length === 1) {
            if (status)
              return new Response(
                JSON.stringify({ detail: "Server failure" }),
                { status }
              )
            throw new TypeError("offline")
          }
        }
        return fetch(path, init)
      })
    )
    render(<EditQuestion card={card} onSaved={() => {}} />)
    await edit()
    const slot = screen.getByRole("group", { name: "Question image" })
    const generate = within(slot).getByRole("button", {
      name: "Generate image (paid)",
    })
    await waitFor(() => expect(generate).toBeEnabled())
    await userEvent.click(generate)
    const check = await within(slot).findByRole("button", {
      name: "Check the same request",
    })
    expect(within(slot).getByLabelText("Image prompt")).toBeDisabled()
    expect(requests).toHaveLength(1)
    await userEvent.click(check)
    expect(requests).toHaveLength(2)
    expect(requests[1]).toEqual(requests[0])
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1)
  }
)

test("ready status with no remaining attempts disables paid generation", async () => {
  paidServer([], { ...availability, remaining: 0, used: 10 })
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  await screen.findByText("Daily attempt limit reached.")
  expect(
    screen
      .getAllByRole("button", { name: "Generate image (paid)" })
      .every((button) => button.hasAttribute("disabled"))
  ).toBe(true)
})

test("a late success poll cannot restore a discarded generation candidate", async () => {
  paidServer([
    {
      id: 21,
      kind: "generate_image",
      card_id: 1,
      slot: "question",
      status: "running",
      result: null,
    },
  ])
  const fetch = globalThis.fetch
  let finishPoll: ((response: Response) => void) | undefined
  let finishDiscard: ((response: Response) => void) | undefined
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string, init?: RequestInit) =>
      path === "/api/jobs/21"
        ? new Promise<Response>((resolve) => {
            finishPoll = resolve
          })
        : path.endsWith("/discard-image")
          ? new Promise<Response>((resolve) => {
              finishDiscard = resolve
            })
          : fetch(path, init)
    )
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await waitFor(() => expect(finishPoll).toBeDefined(), { timeout: 2000 })
  await userEvent.click(
    within(slot).getByRole("button", { name: "Discard image generation" })
  )
  await act(async () => {
    finishPoll!(
      new Response(
        JSON.stringify({
          id: 21,
          kind: "generate_image",
          card_id: 1,
          slot: "question",
          status: "succeeded",
          result: { candidate: { ...draft, origin: "generated" } },
        })
      )
    )
  })
  await act(async () => {
    finishDiscard!(new Response(JSON.stringify({ discarded: true })))
  })
  await waitFor(() =>
    expect(
      within(slot).getByRole("button", { name: "Generate image (paid)" })
    ).toBeEnabled()
  )
  expect(
    within(slot).queryByRole("button", { name: "Use draft" })
  ).not.toBeInTheDocument()
})

test("regeneration compares the original answer and illustrations with the new text", async () => {
  server()
  const fetch = globalThis.fetch
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const response = await fetch(path, init)
      if (path !== "/api/jobs/9") return response
      const data = await response.json()
      data.result.candidate.answer = "New answer"
      return new Response(JSON.stringify(data))
    })
  )
  render(<RegenerateQuestion card={card} onSaved={() => {}} />)
  await userEvent.click(
    screen.getByRole("button", { name: "Regenerate question" })
  )
  await screen.findByText("New answer")
  const original = screen.getByText("Original question").parentElement!
  expect(within(original).getByText("Nil", { exact: true })).toBeVisible()
  expect(within(original).getByRole("img", { name: "Old river" })).toBeVisible()
})

test.each([
  ["lt", "Mokomoji iliustracija be teksto", "Kokia upė?"],
  ["de", "Assignment language: de", "Welcher Fluss?"],
])(
  "%s assignment controls the default image prompt under an English interface",
  async (language, instruction, question) => {
    paidServer()
    render(
      <EditQuestion card={{ ...card, language, question }} onSaved={() => {}} />
    )
    await edit()
    const prompt = within(
      screen.getByRole("group", { name: "Question image" })
    ).getByLabelText("Image prompt") as HTMLTextAreaElement
    expect(prompt.value).toContain(instruction)
    expect(prompt.value).toContain(question)
    if (language === "de")
      expect(prompt.value).toContain("requested text must be in de")
  }
)

test("budget reset uses the selected Polish UI locale and the configured budget timezone", async () => {
  localStorage.setItem("learning-ui-language", "pl")
  paidServer()
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await userEvent.click(screen.getByRole("button", { name: "Edytuj pytanie" }))
  expect(
    await screen.findByText(
      "Odnowienie limitu: 15 paź 2026, 00:00 (Europe/Vilnius)"
    )
  ).toBeVisible()
})

test.each(["truncated JSON", "body read failure", "invalid job envelope"])(
  "unreadable successful paid response (%s) preserves its endpoint, body and key",
  async (failure) => {
    paidServer()
    const fetch = globalThis.fetch
    const requests: { path: string; body: unknown }[] = []
    vi.stubGlobal(
      "fetch",
      vi.fn(async (path: string, init?: RequestInit) => {
        if (path.endsWith("/generate-image")) {
          requests.push({ path, body: JSON.parse(String(init?.body)) })
          if (requests.length === 1) {
            if (failure === "truncated JSON")
              return new Response('{"id":21,"status":', { status: 200 })
            if (failure === "invalid job envelope")
              return new Response(
                JSON.stringify({ id: 21, status: "queued" }),
                { status: 200 }
              )
            const response = new Response("{}", { status: 200 })
            vi.spyOn(response, "json").mockRejectedValue(
              new TypeError("body interrupted")
            )
            return response
          }
        }
        return fetch(path, init)
      })
    )
    render(<EditQuestion card={card} onSaved={() => {}} />)
    await edit()
    const slot = screen.getByRole("group", { name: "Question image" })
    const generate = within(slot).getByRole("button", {
      name: "Generate image (paid)",
    })
    await waitFor(() => expect(generate).toBeEnabled())
    await userEvent.click(generate)
    const check = await within(slot).findByRole("button", {
      name: "Check the same request",
    })
    expect(generate).toBeDisabled()
    expect(within(slot).getByLabelText("Image prompt")).toBeDisabled()
    expect(requests).toHaveLength(1)
    await userEvent.click(check)
    expect(requests).toHaveLength(2)
    expect(requests[1]).toEqual(requests[0])
    expect(generate).toBeDisabled()
    expect(
      within(slot).getByText(
        "Image generation in progress. You can return later."
      )
    ).toBeVisible()
  }
)

test("an unreadable job poll retains pending state and cannot expose fresh paid generation", async () => {
  paidServer([
    {
      id: 21,
      kind: "generate_image",
      card_id: 1,
      slot: "question",
      status: "running",
      result: null,
    },
  ])
  const fetch = globalThis.fetch
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) =>
      path === "/api/jobs/21"
        ? new Response('{"id":21,"status":', { status: 200 })
        : fetch(path, init)
    )
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await within(slot).findByRole("alert", {}, { timeout: 2500 })
  expect(
    within(slot).getByRole("button", { name: "Generate image (paid)" })
  ).toBeDisabled()
  expect(
    within(slot).getByText(
      "Image generation in progress. You can return later."
    )
  ).toBeVisible()
})

test("lost free-save acknowledgement can be replayed without a paid request", async () => {
  const calls = paidServer([
    {
      id: 21,
      kind: "generate_image",
      card_id: 1,
      slot: "question",
      status: "failed",
      result: { can_retry_save: true },
    },
  ])
  const serverFetch = globalThis.fetch
  let lost = false
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      const response = await serverFetch(path, init)
      if (path.endsWith("/retry-image-save") && !lost) {
        lost = true
        throw new Error("Acknowledgement lost")
      }
      return response
    })
  )
  render(<EditQuestion card={card} onSaved={() => {}} />)
  await edit()
  const slot = screen.getByRole("group", { name: "Question image" })
  await userEvent.click(
    await within(slot).findByRole("button", {
      name: "Retry saving image (free)",
    })
  )
  await screen.findByText(
    "Cannot connect to the server. Check your connection and try again."
  )
  await userEvent.click(
    within(slot).getByRole("button", { name: "Check the same request" })
  )
  await within(slot).findByRole("button", { name: "Use draft" })
  expect(
    calls.filter((call) => call.method === "POST").map((call) => call.path)
  ).toEqual(["/api/jobs/21/retry-image-save", "/api/jobs/21/retry-image-save"])
})
