import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { beforeEach, afterEach, expect, test, vi } from "vitest"
import VoiceAnswer, {
  isAudioDTO,
  recordingMime,
} from "../src/features/exercises/VoiceAnswer"

const audio = {
  audio_answer_id: "a".repeat(32),
  job_id: 4,
  status: "ready",
  duration: 2,
  expires_at: "2026-10-16T10:00:00Z",
  original_transcript: "A green tree.",
  expected_language: "en-GB",
  detected_languages: ["en"],
  language_mismatch: false,
  recording_available: false,
  error_code: null,
  error: null,
}
let stopTrack: ReturnType<typeof vi.fn>
class FakeRecorder {
  static current: FakeRecorder
  static isTypeSupported = vi.fn((mime: string) => mime === "audio/mp4")
  state = "inactive"
  mimeType = "audio/mp4"
  ondataavailable: ((e: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    FakeRecorder.current = this
  }
  start() {
    this.state = "recording"
  }
  stop() {
    this.state = "inactive"
    this.ondataavailable?.({
      data: new Blob(["sound"], { type: this.mimeType }),
    })
    this.onstop?.()
  }
}
function setup(current: unknown = null, response: unknown = audio) {
  const posts: RequestInit[] = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        posts.push(init)
        return new Response(JSON.stringify(response), { status: 202 })
      }
      return new Response(
        JSON.stringify({
          available: true,
          reason: null,
          audio_answer: typeof current === "function" ? current() : current,
        })
      )
    })
  )
  const transcript = vi.fn()
  const view = render(
    <VoiceAnswer
      sessionId={8}
      position={0}
      language="en-GB"
      visible
      disabled={false}
      onTranscript={transcript}
    />
  )
  return { posts, transcript, ...view }
}
beforeEach(() => {
  localStorage.setItem("learning-ui-language", "en")
  sessionStorage.clear()
  stopTrack = vi.fn()
  vi.stubGlobal("MediaRecorder", FakeRecorder)
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => ({
        getTracks: () => [{ stop: stopTrack }],
      })),
    },
  })
  URL.createObjectURL = vi.fn(() => "blob:local-audio")
  URL.revokeObjectURL = vi.fn()
})
afterEach(() => vi.useRealTimers())
test("local MP4 record/replay, explicit transcribe, and unmount cleanup", async () => {
  const { posts, transcript, unmount } = setup()
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record" })).toBeEnabled()
  )
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Record" }))
  await screen.findByRole("button", { name: "Stop recording" })
  expect(recordingMime()).toBe("audio/mp4")
  expect(posts).toHaveLength(0)
  fireEvent.click(screen.getByRole("button", { name: "Stop recording" }))
  expect(stopTrack).toHaveBeenCalled()
  expect(screen.getByLabelText("Listen to recording")).toHaveAttribute(
    "src",
    "blob:local-audio"
  )
  expect(posts).toHaveLength(0)
  fireEvent.click(screen.getByRole("button", { name: "Transcribe (paid)" }))
  await waitFor(() => expect(transcript).toHaveBeenCalledWith(audio))
  expect(posts).toHaveLength(1)
  expect((posts[0].body as FormData).get("position")).toBe("0")
  unmount()
  expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:local-audio")
})
test("recording stops at 180 seconds and tab hiding releases media", async () => {
  setup()
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record" })).toBeEnabled()
  )
  vi.useFakeTimers()
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Record" }))
  })
  await act(async () => {
    vi.advanceTimersByTime(180000)
  })
  expect(FakeRecorder.current.state).toBe("inactive")
  expect(stopTrack).toHaveBeenCalled()
  fireEvent.click(screen.getByRole("button", { name: "Record again" }))
  await act(async () => {})
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "hidden",
  })
  fireEvent(document, new Event("visibilitychange"))
  expect(FakeRecorder.current.state).toBe("inactive")
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  })
})
test("permission denial and unsupported recording leave text fallback available", async () => {
  vi.mocked(navigator.mediaDevices.getUserMedia).mockRejectedValue(
    new Error("denied")
  )
  const { posts } = setup()
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record" })).toBeEnabled()
  )
  fireEvent.click(screen.getByRole("button", { name: "Record" }))
  expect(await screen.findByText(/Microphone unavailable/)).toBeVisible()
  expect(posts).toHaveLength(0)
})
test.each([
  {},
  { ...audio, audio_answer_id: 1 },
  { ...audio, duration: Infinity },
  { ...audio, detected_languages: [4] },
  { ...audio, original_transcript: null },
])("malformed DTO rejected %j", (value) =>
  expect(isAudioDTO(value, "en-GB")).toBe(false)
)
test("reload recovers original regional transcript with no paid request", async () => {
  const { transcript, posts } = setup(audio)
  await waitFor(() => expect(transcript).toHaveBeenCalledWith(audio))
  expect(posts).toHaveLength(0)
})
test("malformed paid acknowledgement retains identical multipart key/bytes for explicit replay", async () => {
  const { posts } = setup(null, {})
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record" })).toBeEnabled()
  )
  fireEvent.click(screen.getByRole("button", { name: "Record" }))
  await screen.findByRole("button", { name: "Stop recording" })
  fireEvent.click(screen.getByRole("button", { name: "Stop recording" }))
  fireEvent.click(screen.getByRole("button", { name: "Transcribe (paid)" }))
  fireEvent.click(
    await screen.findByRole("button", { name: "Check transcription again" })
  )
  await waitFor(() => expect(posts).toHaveLength(2))
  expect((posts[0].body as FormData).get("idempotency_key")).toBe(
    (posts[1].body as FormData).get("idempotency_key")
  )
})

test("unsupported MIME never requests microphone", async () => {
  FakeRecorder.isTypeSupported
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(false)
    .mockReturnValueOnce(false)
  setup()
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record" })).toBeEnabled()
  )
  fireEvent.click(screen.getByRole("button", { name: "Record" }))
  await screen.findByText(/Microphone unavailable/)
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
})
test.each(["hide", "switch", "unmount"])(
  "deferred recording deletion after %s never requests microphone",
  async (cancel) => {
    const view = setup(audio)
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Record again" })).toBeEnabled()
    )
    let resolveDelete!: (response: Response) => void
    const deleted = vi.fn()
    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      if (init?.method === "DELETE") {
        deleted()
        return new Promise<Response>((resolve) => {
          resolveDelete = resolve
        })
      }
      return new Response(
        JSON.stringify({ available: true, reason: null, audio_answer: audio })
      )
    })
    fireEvent.click(screen.getByRole("button", { name: "Record again" }))
    await waitFor(() => expect(deleted).toHaveBeenCalledOnce())
    try {
      if (cancel === "hide") {
        Object.defineProperty(document, "visibilityState", {
          configurable: true,
          value: "hidden",
        })
        fireEvent(document, new Event("visibilitychange"))
      } else if (cancel === "switch") {
        view.rerender(
          <VoiceAnswer
            sessionId={8}
            position={0}
            language="en-GB"
            visible={false}
            disabled={false}
            onTranscript={view.transcript}
          />
        )
      } else {
        view.unmount()
      }
      await act(async () => {
        resolveDelete(new Response(JSON.stringify({ discarded: true })))
      })
      expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
    } finally {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      })
    }
  }
)
test("microphone permission resolving after unmount releases every track", async () => {
  let resolve!: (value: MediaStream) => void
  vi.mocked(navigator.mediaDevices.getUserMedia).mockReturnValue(
    new Promise((r) => {
      resolve = r
    })
  )
  const view = setup()
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Record" })).toBeEnabled()
  )
  fireEvent.click(screen.getByRole("button", { name: "Record" }))
  view.unmount()
  await act(async () =>
    resolve({
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream)
  )
  expect(stopTrack).toHaveBeenCalledTimes(1)
})
test.each(["quota_exceeded", "unknown"])(
  "%s is neutral, read-only reload and fresh explicit paid retry",
  async (error_code) => {
    const { posts } = setup({
      ...audio,
      status: error_code === "unknown" ? "unknown" : "failed",
      original_transcript: null,
      recording_available: true,
      error_code,
    })
    const retry = await screen.findByRole("button", {
      name: "Retry transcription (paid)",
    })
    expect(retry).toBeDisabled()
    expect(posts).toHaveLength(0)
    expect(screen.getByLabelText("Listen to recording")).toHaveAttribute(
      "src",
      `/api/audio-answers/${audio.audio_answer_id}/recording`
    )
    fireEvent.click(
      screen.getByRole("checkbox", { name: /I understand another request/ })
    )
    fireEvent.click(retry)
    await waitFor(() => expect(posts).toHaveLength(1))
    expect(JSON.parse(posts[0].body as string)).toMatchObject({
      acknowledge_extra_cost: true,
    })
  }
)
test("uncertain upload reload performs only lookup and restores transcript, without paid resend", async () => {
  sessionStorage.setItem(
    "voice-v1:8:0",
    JSON.stringify({ key: "old-upload", retryId: null })
  )
  const { posts, transcript } = setup(audio)
  await waitFor(() => expect(transcript).toHaveBeenCalledWith(audio))
  expect(posts).toHaveLength(0)
  fireEvent.click(
    screen.getByRole("button", { name: "Check transcription again" })
  )
  await waitFor(() => expect(sessionStorage.getItem("voice-v1:8:0")).toBeNull())
  expect(posts).toHaveLength(0)
})
test("unknown language is never displayed as a confident match", async () => {
  setup({ ...audio, detected_languages: [] })
  expect(await screen.findByText("Recording language is unknown")).toBeVisible()
  expect(
    screen.queryByText("Recording language matches the assignment")
  ).not.toBeInTheDocument()
})
test("one-sided word targets are readable in every interface language", async () => {
  const { wordTarget } = await import("../src/lib/word-target")
  for (const locale of ["pl", "en", "ru"]) {
    localStorage.setItem("learning-ui-language", locale)
    expect(wordTarget(5, 100, null)).not.toContain("—")
    expect(wordTarget(5, null, 150)).not.toContain("—")
    expect(wordTarget(5, null, null)).not.toContain("—")
  }
})
test("malformed voice metadata cannot release grading request", async () => {
  const { isEvaluationFeedback } =
    await import("../src/features/exercises/FreeResponse")
  const feedback = {
    session_id: 8,
    position: 0,
    next_position: 1,
    evaluation_id: 9,
    card: {
      id: 1,
      question: "Describe the tree",
      question_type: "free_response",
      sources: [],
      exercise: {
        model_answer: "A green tree.",
        rubric: [{ id: "r", label: "Clarity", weight: 100 }],
        expected_points: [{ id: "p", text: "Tree", essential: true }],
      },
    },
    input_method: "voice",
    voice: {
      original_transcript: "A green tree.",
      original_word_count: 3,
      was_edited: true,
    },
    correct: true,
    score: 100,
    word_count: 4,
    word_count_version: 1,
    word_limit: { min: null, max: null, met: true },
    language_match: true,
    rubric_scores: [{ criterion_id: "r", score: 4, explanation: "Clear" }],
    point_checks: [{ point_id: "p", met: true, evidence: [] }],
    corrections: [],
    summary: "Clear description",
    suggestions: [],
  }
  expect(isEvaluationFeedback(feedback)).toBe(true)
  expect(
    isEvaluationFeedback({
      ...feedback,
      voice: { ...feedback.voice, original_transcript: {} },
    })
  ).toBe(false)
})

test("a recording discarded in another tab invalidates the selected voice answer", async () => {
  vi.useFakeTimers()
  let current: unknown = audio
  const { transcript } = setup(() => current)
  await act(async () => {})
  expect(transcript).toHaveBeenCalledWith(audio)
  current = null
  await act(async () => {
    vi.advanceTimersByTime(1600)
  })
  expect(transcript).toHaveBeenLastCalledWith(null)
})

test("missing retained audio releases definitive retry rejection for explicit re-recording", async () => {
  const current = {
    ...audio,
    status: "failed",
    original_transcript: null,
    recording_available: true,
    error_code: "failed",
  }
  setup(current)
  await screen.findByRole("button", { name: "Retry transcription (paid)" })
  const paid = vi.fn()
  vi.mocked(fetch).mockImplementation(async (_url, init) => {
    if (init?.method === "POST") {
      paid()
      return new Response(
        JSON.stringify({
          detail: { code: "record_again", message: "Missing recording" },
        }),
        { status: 409 }
      )
    }
    if (init?.method === "DELETE")
      return new Response(JSON.stringify({ discarded: true }))
    return new Response(
      JSON.stringify({ available: true, reason: null, audio_answer: current })
    )
  })
  fireEvent.click(screen.getByRole("checkbox"))
  fireEvent.click(
    screen.getByRole("button", { name: "Retry transcription (paid)" })
  )
  await screen.findByText("The recording is no longer available. Record again.")
  expect(
    screen.queryByRole("button", { name: "Check transcription again" })
  ).not.toBeInTheDocument()
  expect(
    screen.queryByRole("button", { name: "Retry transcription (paid)" })
  ).not.toBeInTheDocument()
  expect(screen.queryByLabelText("Listen to recording")).not.toBeInTheDocument()
  expect(sessionStorage.getItem("voice-v1:8:0")).toBeNull()
  fireEvent.click(screen.getByRole("button", { name: "Record again" }))
  await screen.findByRole("button", { name: "Stop recording" })
  expect(paid).toHaveBeenCalledTimes(1)
  expect(navigator.mediaDevices.getUserMedia).toHaveBeenCalledTimes(1)
})

test.each([null, "record_again", { code: "conflict" }])(
  "ambiguous retry409 keeps its key and blocks replacement: %j",
  async (detail) => {
    const current = {
      ...audio,
      status: "failed",
      original_transcript: null,
      recording_available: true,
      error_code: "failed",
    }
    setup(current)
    await screen.findByRole("button", { name: "Retry transcription (paid)" })
    const paid = vi.fn()
    vi.mocked(fetch).mockImplementation(async (_url, init) => {
      if (init?.method === "POST") {
        paid()
        return new Response(JSON.stringify({ detail }), { status: 409 })
      }
      return new Response(
        JSON.stringify({ available: true, reason: null, audio_answer: current })
      )
    })
    fireEvent.click(screen.getByRole("checkbox"))
    fireEvent.click(
      screen.getByRole("button", { name: "Retry transcription (paid)" })
    )
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Check transcription again" })
      ).toBeEnabled()
    )
    expect(screen.getByRole("button", { name: "Record again" })).toBeDisabled()
    expect(JSON.parse(sessionStorage.getItem("voice-v1:8:0")!).retryId).toBe(
      audio.audio_answer_id
    )
    expect(paid).toHaveBeenCalledTimes(1)
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  }
)
