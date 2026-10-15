import { expect, test } from "@playwright/test"
import { translations } from "../src/locales"

for (const locale of ["en", "pl", "ru"] as const)
  test(`${locale} record transcribe edit grade recover history private deletion`, async ({
    page,
    context,
    browserName,
  }, info) => {
    const errors: string[] = []
    const nativeMediaDiagnostics: string[] = []
    const mediaRequestFailures: string[] = []
    page.on("requestfailed", (request) => {
      if (
        request.url().startsWith("blob:") ||
        request.url().includes("/api/audio-answers/")
      )
        mediaRequestFailures.push(
          `${request.url()}: ${request.failure()?.errorText}`
        )
    })
    page.on("pageerror", (e) => errors.push(e.message))
    page.on("console", (message) => {
      if (
        browserName === "webkit" &&
        message.location().url === "" &&
        /^Button failed to load, iconName = (invalid|pip|airplay)-placard, layoutTraits = \[MacOSLayoutTraits Inline\], src = blob:/.test(
          message.text()
        )
      ) {
        nativeMediaDiagnostics.push(message.text())
        return
      }
      if (
        message.type() === "error" &&
        !(
          message.location().url.endsWith("/api/auth/me") &&
          message.text().includes("401")
        )
      )
        errors.push(message.text())
    })
    const label = (english: string) => {
      const entry = Object.entries(translations).find(
        ([, value]) => value.en === english
      )
      return !entry || locale === "en"
        ? english
        : locale === "ru"
          ? entry[0]
          : entry[1].pl
    }
    await page.addInitScript(() =>
      localStorage.setItem("learning-ui-language", "en")
    )
    await page.goto("/")
    await page
      .getByLabel("Interface language", { exact: true })
      .selectOption("en")
    await page.getByLabel("Username", { exact: true }).fill("child")
    await page
      .getByLabel("Password", { exact: true })
      .fill("browser-child-password")
    await page.getByRole("button", { name: "Sign in", exact: true }).click()
    await expect(
      page.getByRole("link", { name: "Library", exact: true })
    ).toBeVisible()
    const me = await (await page.request.get("/api/auth/me")).json()
    const headers = {
      "X-CSRF-Token": me.csrf_token,
      Origin: new URL(page.url()).origin,
    }
    const topics = await (await page.request.get("/api/topics")).json()
    const topic = topics.find(
      (row: { name: string }) => row.name === "Voice QA"
    )
    expect(topic).toBeTruthy()
    const session = await (
      await page.request.post("/api/study", {
        headers,
        data: {
          topic_ids: [topic.id],
          mode: "quiz",
          question_types: ["free_response"],
          include_ai_evaluated: true,
        },
      })
    ).json()
    await page.goto(`/#study/${session.id}`)
    await page
      .getByLabel("Interface language", { exact: true })
      .selectOption(locale)
    let paid = 0
    page.on("request", (req) => {
      if (req.method() === "POST" && /\/(audio|answer|retry)$/.test(req.url()))
        paid++
    })
    if (browserName === "webkit") {
      // Controlled MP4 recorder boundary: browser UI/MIME path and server decoder remain real.
      const { execFileSync } = await import("node:child_process")
      const mp4 = execFileSync("ffmpeg", [
        "-nostdin",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=duration=2",
        "-c:a",
        "aac",
        "-f",
        "mp4",
        "-movflags",
        "frag_keyframe+empty_moov",
        "pipe:1",
      ]).toString("base64")
      await page.evaluate((data) => {
        Object.defineProperty(navigator, "mediaDevices", {
          configurable: true,
          value: {
            getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }),
          },
        })
        class Recorder {
          static isTypeSupported(mime: string) {
            return mime === "audio/mp4"
          }
          state = "inactive"
          mimeType = "audio/mp4"
          ondataavailable?: (e: { data: Blob }) => void
          onstop?: () => void
          start() {
            this.state = "recording"
          }
          stop() {
            this.state = "inactive"
            this.ondataavailable?.({
              data: new Blob(
                [Uint8Array.from(atob(data), (c) => c.charCodeAt(0))],
                { type: "audio/mp4" }
              ),
            })
            this.onstop?.()
          }
        }
        Object.defineProperty(window, "MediaRecorder", {
          configurable: true,
          value: Recorder,
        })
      }, mp4)
    }
    await page.getByRole("button", { name: label("Tell"), exact: true }).click()
    await page
      .getByRole("button", { name: label("Record"), exact: true })
      .click()
    await expect(page.getByRole("timer")).toBeVisible()
    await expect(page.getByLabel(label("Your written response"))).toHaveCount(0)
    await page.waitForTimeout(400)
    await page.getByRole("button", { name: label("Stop recording") }).click()
    await expect(page.getByLabel(label("Listen to recording"))).toBeVisible()
    expect(paid).toBe(0)
    const playback = await page
      .locator("audio")
      .evaluate(async (element: HTMLAudioElement) => {
        element.load()
        let playError: string | null = null
        try {
          await Promise.race([
            element.play(),
            new Promise((_, reject) =>
              setTimeout(() => reject(new Error("Playback timeout")), 5000)
            ),
          ])
        } catch (error) {
          playError = String(error)
        }
        const start = element.currentTime
        const deadline = Date.now() + 3000
        while (
          element.currentTime <= start &&
          !element.ended &&
          Date.now() < deadline
        )
          await new Promise((resolve) => setTimeout(resolve, 100))
        const result = {
          playError,
          error: element.error?.code ?? null,
          readyState: element.readyState,
          duration: element.duration,
          currentTime: element.currentTime,
          progressed: element.currentTime > start,
          paused: element.paused,
          ended: element.ended,
          mp4: element.canPlayType("audio/mp4"),
          wav: element.canPlayType("audio/wav"),
        }
        element.pause()
        return result
      })
    const { writeFile: writePlayback } = await import("node:fs/promises")
    await writePlayback(
      `/tmp/voice-${locale}-playback-${info.project.name}.json`,
      JSON.stringify(playback)
    )
    expect(playback.playError).toBeNull()
    expect(playback.error).toBeNull()
    expect(playback.progressed).toBe(true)
    await page.screenshot({
      path: `/tmp/voice-${locale}-local-${info.project.name}.png`,
      fullPage: true,
    })
    if (locale === "en" && browserName !== "webkit")
      await page.route(`**/api/study/${session.id}/audio`, async (route) => {
        const response = await route.fetch()
        await route.fulfill({
          response,
          body: "{}",
          contentType: "application/json",
        })
      })
    await page
      .getByRole("button", { name: label("Transcribe (paid)") })
      .dblclick()
    if (locale !== "en" || browserName === "webkit") {
      const privateAudio = page.locator('audio[src^="/api/audio-answers/"]')
      await expect(privateAudio).toBeVisible()
      const privatePlayback = await privateAudio.evaluate(
        async (element: HTMLAudioElement) => {
          element.load()
          let playError: string | null = null
          try {
            await element.play()
          } catch (error) {
            playError = String(error)
          }
          const deadline = Date.now() + 3000
          while (element.currentTime <= 0 && Date.now() < deadline)
            await new Promise((resolve) => setTimeout(resolve, 100))
          const result = {
            playError,
            error: element.error?.code ?? null,
            readyState: element.readyState,
            duration: element.duration,
            currentTime: element.currentTime,
          }
          element.pause()
          return result
        }
      )
      await writePlayback(
        `/tmp/voice-${locale}-private-playback-${info.project.name}.json`,
        JSON.stringify(privatePlayback)
      )
      expect(privatePlayback.playError).toBeNull()
      expect(privatePlayback.error).toBeNull()
      expect(privatePlayback.currentTime).toBeGreaterThan(0)
    }
    const input = page.getByLabel(label("Your written response"))
    await expect(input).toHaveValue("A green tree grows here.")
    expect(paid).toBe(1)
    await page.reload()
    // The init script resets locale on navigation; choose again.
    await page
      .getByLabel("Interface language", { exact: true })
      .selectOption(locale)
    await expect(input).toHaveValue("A green tree grows here.")
    if (locale === "en" && browserName !== "webkit") {
      await page
        .getByRole("button", { name: label("Check transcription again") })
        .click()
      expect(paid).toBe(1)
    }
    await input.fill("A green tree grows in the garden.")
    await expect(
      page.getByText(label("The edited transcript is graded"))
    ).toBeVisible()
    await expect(
      page.getByText(label("Words: {count}").replace("{count}", "7"), {
        exact: true,
      })
    ).toBeVisible()
    expect(paid).toBe(1)
    const current = await (
      await page.request.get(`/api/study/${session.id}/audio?position=0`)
    ).json()
    const id = current.audio_answer.audio_answer_id
    expect(current.audio_answer.expected_language).toBe("en-GB")
    expect(
      (await page.request.get(`/api/audio-answers/${id}/recording`)).status()
    ).toBe(404)
    const viewport = await page.locator(".skip-link").evaluate((element) => ({
      rect: element.getBoundingClientRect().toJSON(),
      active: document.activeElement?.id,
    }))
    expect(viewport.rect.bottom).toBeLessThanOrEqual(0)
    const { writeFile } = await import("node:fs/promises")
    await writeFile(
      `/tmp/voice-${locale}-viewport-${info.project.name}.json`,
      JSON.stringify(viewport)
    )
    await page.screenshot({
      path: `/tmp/voice-${locale}-viewport-${info.project.name}.png`,
      fullPage: false,
    })
    await page.screenshot({
      path: `/tmp/voice-${locale}-review-${info.project.name}.png`,
      fullPage: true,
    })
    await page
      .getByRole("button", { name: label("Grade with AI (paid)") })
      .click()
    await expect(
      page.getByText(label("Score: {score}/100").replace("{score}", "75"))
    ).toBeVisible()
    expect(paid).toBe(2)
    await page.reload()
    await page
      .getByLabel("Interface language", { exact: true })
      .selectOption(locale)
    await expect(
      page.getByText(label("The edited transcript is graded"))
    ).toBeVisible()
    await expect(
      page.getByText(label("Audio is not kept in history"))
    ).toBeVisible()
    const stored = await (
      await page.request.get(`/api/study/${session.id}`)
    ).json()
    expect(stored.review[0].voice).toEqual({
      original_transcript: "A green tree grows here.",
      original_word_count: 5,
      was_edited: true,
    })
    const foreign = await context
      .browser()!
      .newContext({ baseURL: new URL(page.url()).origin })
    await foreign.request.post("/api/auth/login", {
      data: { username: "parent", password: "browser-parent-password" },
      headers: { Origin: new URL(page.url()).origin },
    })
    expect(
      (await foreign.request.get(`/api/audio-answers/${id}`)).status()
    ).toBe(404)
    await foreign.close()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
    await page.screenshot({
      path: `/tmp/voice-${locale}-history-${info.project.name}.png`,
      fullPage: true,
    })
    expect(
      (
        await page.request.post("/api/study/delete", {
          headers,
          data: { session_ids: [session.id] },
        })
      ).ok()
    ).toBeTruthy()
    expect((await page.request.get(`/api/audio-answers/${id}`)).status()).toBe(
      404
    )
    await writeFile(
      `/tmp/voice-${locale}-console-${info.project.name}.json`,
      JSON.stringify({ errors, nativeMediaDiagnostics, mediaRequestFailures })
    )
    expect(errors).toEqual([])
  })

test("permission denial, unknown/quota recovery and text fallback never send an implicit paid request", async ({
  page,
}, info) => {
  await page.addInitScript(() =>
    localStorage.setItem("learning-ui-language", "en")
  )
  await page.goto("/")
  await page.getByLabel("Username", { exact: true }).fill("child")
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser-child-password")
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await expect(
    page.getByRole("link", { name: "Library", exact: true })
  ).toBeVisible()
  const me = await (await page.request.get("/api/auth/me")).json()
  const headers = {
    "X-CSRF-Token": me.csrf_token,
    Origin: new URL(page.url()).origin,
  }
  const topics = await (await page.request.get("/api/topics")).json()
  const topic = topics.find((row: { name: string }) => row.name === "Voice QA")
  const session = await (
    await page.request.post("/api/study", {
      headers,
      data: {
        topic_ids: [topic.id],
        mode: "quiz",
        question_types: ["free_response"],
        include_ai_evaluated: true,
      },
    })
  ).json()
  await page.goto(`/#study/${session.id}`)
  let paid = 0
  page.on("request", (req) => {
    if (req.method() === "POST" && /\/(audio|answer|retry)$/.test(req.url()))
      paid++
  })
  await page.evaluate(() => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: async () => {
          throw new DOMException("denied", "NotAllowedError")
        },
      },
    })
  })
  await page.getByRole("button", { name: "Tell", exact: true }).click()
  await page.getByRole("button", { name: "Record", exact: true }).click()
  await expect(page.getByText(/Microphone unavailable/)).toBeVisible()
  await page.getByRole("button", { name: "Write", exact: true }).click()
  const input = page.getByLabel("Your written response")
  await input.focus()
  await page.keyboard.type("I can still write.")
  expect(paid).toBe(0)
  // Controlled server states verify neutral UI; actual quota/reservation/timeout paths
  // are separately covered by SDK-boundary backend tests.
  for (const error_code of ["unknown", "quota_exceeded"]) {
    await page.route(`**/api/study/${session.id}/audio?position=0`, (route) =>
      route.fulfill({
        json: {
          available: true,
          reason: null,
          audio_answer: {
            audio_answer_id: "a".repeat(32),
            job_id: 1,
            status: error_code === "unknown" ? "unknown" : "failed",
            duration: 1,
            expires_at: "2099-01-01T00:00:00Z",
            original_transcript: null,
            expected_language: "en-GB",
            detected_languages: [],
            language_mismatch: false,
            recording_available: true,
            error_code,
            error: null,
          },
        },
      })
    )
    await page.reload()
    await page.getByRole("button", { name: "Tell", exact: true }).click()
    const retry = page.getByRole("button", {
      name: "Retry transcription (paid)",
    })
    await expect(retry).toBeDisabled()
    await expect(
      page.getByText(
        error_code === "unknown"
          ? /Result unknown/
          : "Daily transcription limit reached"
      )
    ).toBeVisible()
    expect(paid).toBe(0)
    await page.screenshot({
      path: `/tmp/voice-${error_code}-${info.project.name}.png`,
      fullPage: true,
    })
    await page.unroute(`**/api/study/${session.id}/audio?position=0`)
  }
})
