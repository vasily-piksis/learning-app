import { expect, test } from "@playwright/test"

const labels = {
  en: {
    input: "Your written response",
    grade: "Grade with AI (paid)",
    pending: "Grading in progress",
    result: "Session result",
    repeat: "Review difficult cards",
    back: "Back to topic",
    score: "Score: 75/100",
    completion: "Assignment not completed yet",
    range: "Word target not met",
    retry: "Retry the same answer (paid)",
    ack: "I understand another request may cost extra",
  },
  pl: {
    input: "Twoja swobodna odpowiedź",
    grade: "Oceń z AI (płatne)",
    pending: "Trwa ocenianie",
    result: "Wynik sesji",
    repeat: "Powtórz trudne pytania",
    back: "Do tematu",
    score: "Wynik: 75/100",
    completion: "Zadanie jeszcze niewykonane",
    range: "Cel słów nieosiągnięty",
    retry: "Ponów tę samą odpowiedź (płatne)",
    ack: "Rozumiem, że kolejne żądanie może kosztować dodatkowo",
  },
  ru: {
    input: "Твой развёрнутый ответ",
    grade: "Оценить с ИИ (платно)",
    pending: "Проверяем ответ",
    result: "Результат занятия",
    repeat: "Повторить сложные карточки",
    back: "К теме",
    score: "Оценка: 75/100",
    completion: "Задание пока не выполнено",
    range: "Диапазон слов не соблюдён",
    retry: "Повторить тот же ответ (платно)",
    ack: "Понимаю, что новый запрос может стоить дополнительно",
  },
}
for (const locale of ["en", "pl", "ru"] as const)
  test(`${locale} Prepare Draft Edit Save Start Answer Pending Result History Repeat; Lithuanian retained`, async ({
    page,
    context,
  }, info) => {
    const errors: string[] = []
    page.on("pageerror", (error) => errors.push(error.message))
    page.on("console", (message) => {
      if (
        message.type() === "error" &&
        !(
          message.location().url.endsWith("/api/auth/me") &&
          message.text().includes("401")
        )
      )
        errors.push(message.text())
    })
    await page.goto("/")
    await page
      .getByLabel("Język interfejsu", { exact: true })
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
    const subjectResponse = await page.request.post("/api/subjects", {
      headers,
      data: { name: `Free ${locale} ${info.project.name}` },
    })
    expect(subjectResponse.ok()).toBeTruthy()
    const subject = await subjectResponse.json()
    const topic = await (
      await page.request.post("/api/topics", {
        headers,
        data: { name: "Lietuvių", subject_id: subject.id },
      })
    ).json()
    await page.goto(`/#library/topic/${topic.id}/materials`)
    await page
      .getByLabel("YouTube link", { exact: true })
      .fill("https://www.youtube.com/watch?v=LTfree12345")
    await page.getByRole("button", { name: "Add YouTube", exact: true }).click()
    await expect(
      page.getByText("Captions: lt · 1 segments", { exact: false })
    ).toBeVisible()
    await page.goto(`/#library/topic/${topic.id}`)
    await page.getByRole("combobox", { name: "Practice method" }).click()
    await page.getByRole("option", { name: /Free response/ }).click()
    await page
      .getByRole("button", { name: "Prepare exercises", exact: true })
      .click()
    await page.getByLabel("How many questions?").fill("1")
    await page.getByRole("radio", { name: "Language and grammar" }).click()
    await expect(
      page.getByRole("button", { name: "Create questions", exact: true })
    ).toBeDisabled()
    await page.getByLabel("Original language code").fill("lt")
    const level = locale === "pl" ? "B2" : "A1"
    await page.getByRole("combobox", { name: "CEFR level" }).click()
    await page.getByRole("option", { name: level, exact: true }).click()
    await page.getByLabel("Minimum words (optional)").fill("100")
    await page.getByLabel("Maximum words (optional)").fill("150")
    if (locale === "en") {
      await expect(page.locator("[data-sonner-toast]")).toHaveCount(0)
      await page.evaluate(() =>
        window.scrollTo({ top: 0, behavior: "instant" })
      )
      await page.evaluate(async () => {
        await document.fonts.ready
        ;(document.activeElement as HTMLElement)?.blur()
        for (const animation of document.getAnimations()) animation.finish()
      })
      await page.screenshot({
        path: `/tmp/free-response-preparation-${info.project.name}.png`,
        animations: "disabled",
        fullPage: true,
      })
      await page
        .getByRole("button", { name: "Create questions", exact: true })
        .scrollIntoViewIfNeeded()
      await page.screenshot({
        path: `/tmp/free-response-preparation-lower-${info.project.name}.png`,
        animations: "disabled",
        fullPage: true,
      })
    }
    await page
      .getByRole("button", { name: "Create questions", exact: true })
      .click()
    await expect(
      page.getByRole("heading", { name: "Review new questions" })
    ).toBeVisible()
    await page.getByRole("button", { name: "Edit card", exact: true }).click()
    await expect(page.getByLabel("Model answer")).toHaveValue(
      "Ąžuolas yra medis. Jis auga miške."
    )
    await expect(page.getByLabel("Criterion 1", { exact: true })).toHaveValue(
      `Aiškumas ${level}`
    )
    if (locale === "en") {
      await page.evaluate(async () => {
        await document.fonts.ready
        ;(document.activeElement as HTMLElement)?.blur()
        for (const animation of document.getAnimations()) animation.finish()
      })
      await page.screenshot({
        path: `/tmp/free-response-criteria-${info.project.name}.png`,
        animations: "disabled",
        fullPage: true,
      })
      await page
        .getByLabel("Criterion weight 1", { exact: true })
        .scrollIntoViewIfNeeded()
      await page.screenshot({
        path: `/tmp/free-response-criteria-rubric-${info.project.name}.png`,
        animations: "disabled",
        fullPage: true,
      })
      await page
        .getByRole("button", { name: "Save changes", exact: true })
        .scrollIntoViewIfNeeded()
      await expect(
        page.getByRole("button", { name: "Save changes", exact: true })
      ).toBeInViewport()
      await page.screenshot({
        path: `/tmp/free-response-criteria-lower-${info.project.name}.png`,
        animations: "disabled",
        fullPage: true,
      })
    }
    await page
      .getByLabel("Criterion 1", { exact: true })
      .fill(`Aiškumas ${level} patikslintas`)
    await page
      .getByRole("button", { name: "Save changes", exact: true })
      .click()
    await expect(page.getByRole("dialog")).not.toBeVisible()
    await page.getByRole("button", { name: "Select all", exact: true }).click()
    await page
      .getByRole("button", { name: "Save selected (1)", exact: true })
      .click()
    await page.getByRole("button", { name: "Go to study", exact: true }).click()
    await page.getByRole("combobox", { name: "Practice method" }).click()
    await page.getByRole("option", { name: /Free response/ }).click()
    await expect(
      page.getByRole("button", { name: "Start studying", exact: true })
    ).toBeDisabled()
    await page.getByRole("checkbox", { name: "Enable paid AI grading" }).check()
    await page
      .getByRole("button", { name: "Start studying", exact: true })
      .click()
    await expect(page).toHaveURL(/#study\/\d+$/)
    const studyUrl = page.url(),
      sessionId = studyUrl.split("/").pop()!
    const studyBefore = await (
      await page.request.get(`/api/study/${sessionId}`)
    ).json()
    expect(studyBefore.card.exercise).not.toHaveProperty("rubric")
    await page
      .getByLabel("Interface language", { exact: true })
      .selectOption(locale)
    const ui = labels[locale]
    const input = page.getByLabel(ui.input)
    await expect(input).toBeEnabled()
    expect(await page.title()).toBeTruthy()
    let paidPosts = 0
    page.on("request", (request) => {
      if (request.method() === "POST" && /\/answer$/.test(request.url()))
        paidPosts++
    })
    await input.focus()
    await page.keyboard.type("Azuolas yra medis.")
    await input.fill("Ąžuolas yra medis.")
    expect(paidPosts).toBe(0)
    await page.screenshot({
      path: `/tmp/free-response-${locale}-input-${info.project.name}.png`,
      animations: "disabled",
      fullPage: true,
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
    await page.getByRole("button", { name: ui.grade, exact: true }).click()
    await expect(input).toBeDisabled()
    await expect(page.getByText(ui.pending, { exact: true })).toBeVisible()
    await page.screenshot({
      path: `/tmp/free-response-${locale}-pending-${info.project.name}.png`,
      animations: "disabled",
      fullPage: true,
    })
    const second = await context.newPage()
    await second.goto(studyUrl)
    await page.reload()
    await expect(page.getByText(ui.score, { exact: true })).toBeVisible()
    await expect(page.getByText(ui.completion, { exact: true })).toBeVisible()
    await expect(
      page.getByText("Geras atsakymas.", { exact: true })
    ).toBeVisible()
    await expect(page.getByText(ui.range, { exact: true })).toBeVisible()
    await expect(
      page.getByText(`Aiškumas ${level} patikslintas: 3/4`, { exact: true })
    ).toBeVisible()
    await page.screenshot({
      path: `/tmp/free-response-${locale}-result-${info.project.name}.png`,
      animations: "disabled",
      fullPage: true,
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
    const completed = await (
      await page.request.get(`/api/study/${sessionId}`)
    ).json()
    expect(completed.answered).toBe(1)
    expect(completed.review[0].submission.free_text).toBe("Ąžuolas yra medis.")
    expect(completed.review[0].word_count).toBe(3)
    await second.close()
    // Reload may already show the completed session. The stored feedback remains visible there.
    if (
      await page.getByRole("button", { name: ui.result, exact: true }).count()
    )
      await page.getByRole("button", { name: ui.result, exact: true }).click()
    await expect(page.getByText(ui.score, { exact: true })).toBeVisible()
    await expect(page.getByText(ui.completion, { exact: true })).toBeVisible()
    await page.goto("/#history")
    await expect(page.locator(`a[href="#study/${sessionId}"]`)).toBeVisible()
    await page.locator(`a[href="#study/${sessionId}"]`).click()
    await expect(page.getByText(ui.score, { exact: true })).toBeVisible()
    await expect(page.getByText(ui.completion, { exact: true })).toBeVisible()
    // Stable button action is located by the existing localized repeat copy.
    await page.getByRole("button", { name: ui.repeat, exact: true }).click()
    await expect(page.getByLabel(ui.input)).toBeEnabled()
    const repeatedId = page.url().split("/").pop()!
    const repeated = await (
      await page.request.get(`/api/study/${repeatedId}`)
    ).json()
    expect(repeated.card.question).toBe(studyBefore.card.question)
    expect(repeated.card.exercise).toEqual(studyBefore.card.exercise)
    if (locale === "en") {
      // Library deletions cannot alter the frozen repeated assignment.
      const documents = await (
        await page.request.get(`/api/topics/${topic.id}/documents`)
      ).json()
      expect(
        (
          await page.request.delete(`/api/cards/${studyBefore.card.id}`, {
            headers,
          })
        ).ok()
      ).toBeTruthy()
      expect(
        (
          await page.request.delete(`/api/documents/${documents[0].id}`, {
            headers,
          })
        ).ok()
      ).toBeTruthy()
      const bodies: unknown[] = []
      let first = true
      await page.route(`**/api/study/${repeatedId}/answer`, async (route) => {
        bodies.push(route.request().postDataJSON())
        const response = await route.fetch()
        if (first) {
          first = false
          await route.fulfill({
            response,
            status: 200,
            body: "unreadable",
            contentType: "application/json",
          })
        } else await route.fulfill({ response })
      })
      await page
        .getByLabel(ui.input)
        .fill(`Ąžuolas nežinoma ${info.project.name}`)
      await page.getByRole("button", { name: ui.grade, exact: true }).click()
      await expect(page.getByLabel(ui.input)).toBeDisabled()
      await page
        .getByRole("button", { name: "Check submission again", exact: true })
        .click()
      expect(bodies).toHaveLength(2)
      expect(bodies[0]).toEqual(bodies[1])
      const retry = page.getByRole("button", { name: ui.retry, exact: true })
      await expect(retry).toBeVisible()
      await expect(retry).toBeDisabled()
      await page.screenshot({
        path: `/tmp/free-response-unknown-${info.project.name}.png`,
        animations: "disabled",
        fullPage: true,
      })
      await page.getByRole("checkbox", { name: ui.ack }).check()
      await retry.click()
      await expect(page.getByText(ui.score, { exact: true })).toBeVisible()
      await expect(page.getByText(ui.completion, { exact: true })).toBeVisible()
      const stored = await (
        await page.request.get(
          `/api/study/${repeatedId}/evaluations?position=0`
        )
      ).json()
      expect(stored.status).toBe("completed")
      expect(stored.submission.free_text).toBe(
        `Ąžuolas nežinoma ${info.project.name}`
      )
      const foreign = await context
        .browser()!
        .newContext({ baseURL: new URL(page.url()).origin })
      const login = await foreign.request.post("/api/auth/login", {
        data: { username: "parent", password: "browser-parent-password" },
        headers: { Origin: new URL(page.url()).origin },
      })
      expect(login.ok()).toBeTruthy()
      expect(
        (
          await foreign.request.get(
            `/api/study/${repeatedId}/evaluations?position=0`
          )
        ).status()
      ).toBe(404)
      await foreign.close()
    }
    await page.getByRole("link", { name: ui.back, exact: true }).first().click()
    await expect(page).toHaveURL(new RegExp(`#library/topic/${topic.id}$`))
    expect(errors).toEqual([])
  })
