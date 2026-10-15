import { expect, test } from "@playwright/test"
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAAExUlEQVR4nO3d4W0USRSFUXtFBEidzeaxmRCEMyEPRA5kgNQSMayEJYv12uPpmaquuvXO+YuAFuLTfd0/4PHHz+8PlTx9+/ywnC9//xr9CIzx16DfF2igXMBLjtWSZwXXKBcwrETAizDCNVUMeMkrmpoqBrwqI1yQgCFY0YBXvaKNcDVFA4Y11A3YCLOAugHDAgS8IG/CdZQOeNUrmjpKB7wwI1yEgCFY9YAXvqKNcAXVA4ZoAoZgAnZFE+zT6AeALrb964Uf3bd/1vhzf6z2j9oV/N6z8Ie6o92uV7ITutxf8VVt+9ej9d78s+Yh4PWtfV88tIgwN2MBk21rF15iw96BqyzVeq8JW7fegl6MLTCRuq7lljPFAq5ipfvihMC2kIYFvPKRuaTT0toSGhZwISuNMM8E/B9GeHInr+I2/QgLuJboER6S0zZ3wwKGYAIud0WHjvDAJdwmHmEBQzABVxQ3wsM3cBv9AO8RcMUrmmUIGIIJuKigK3qS83Wb4zFeEfDbXNFEEHBdQSPMewQMwQRc+oo2wukEDMEEXJ0Rjibg6lc00QSMEQ4mYAgm4A8UuaJnfhOe5B953ed4jFcEDMEE/DEjzLQETIDh5+s++gHeI2Ay3oR5k4CvUuSKntnADdxnnV8BQzYLTMwVPWQJ94nnV8AHuKJncHJO+9z1CpiwEeYVJzRhTlvFffr5FfAxda7oyUf4hLT2hHoFTKquge0h9QqY1BF+zmxvXVqPX7Mr78DH1LmiU+ztestK95mACR7hVrMZN7wvPo1+AGhj/13g0f8/IbTbF48/fn4f/Qx5Uqap8lvDdrHk9G5fWGDWtK+S6GXegflAqXMjjoALXZWsR8B8zAhPS8A3MsLMQMBcxQjPScAQTMC3c0UznIC5lit6QgKGYAK+S7Ur2gjPRsAQTMAcY4SnIuB7VbuimYqAOcwIz0PAEEzADRS8oo3wJAQMwQTMjYzwDATcRsErmhkImNsZ4eEEDMEE3EzNK9oIjyVgCCbglmqOMAMJmHu5ogcSMAQTcGM1r2gjPIqAIZiAacMIDyHg9mpe0QwhYJoxwucTMAQTcBdlr2gjfDIBQzAB05gRPpOAIZiAeyn7GmyEzyRgCCZguvAmfA4BQzAB04sRPoGAO6r8HYtzCBiCCZiOXNG9CRiCCZi+jHBXAoZgAu7Lh2gj3JWAIZiAOYM34U4EDMEEzEmMcA8C7s53LPoRMOcxws0JGIIJmFMZ4bYEDMEEfAbfsf5khBsSMAQTMAQTMAO4olsRMAQTMGMY4SYEfBIfoulBwAxjhO8nYAgmYEYywncSMAQT8Hl8x3qTEb6HgCGYgBnPCN9MwBBMwEzBCN9GwKfyHYu2BMwsjPANBAzBBMxEjPBRAoZgAoZgAj6bD9GXuaIPETAEEzDTMcLXEzAEEzAzMsJXEvAAvmPRioCZlBG+hoAhmICZlxH+kIAhmIDH8B3rSkb4MgFDMAEzOyN8gYAhmIAJYITfI2AIJuBhfIjmfgImgyv6TQKGYAImhhH+PwFDMAGP5DvWUUb4FQFDMAETxgj/ScAQTMDkMcIvBDyY71jcQ8BEMsLPBAzBBEyqp2+fRz/CeAKGYAIm2FP5ERbweD5EczMBk+2p9gj/C5hcNgR3ItJRAAAAAElFTkSuQmCC",
  "base64"
)

test("private upload drafts, immutable study/repeat images and final reference cleanup", async ({
  page,
  browser,
}, info) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  page.on("console", (msg) => {
    if (msg.type() === "error" && !msg.text().includes("status of"))
      errors.push(msg.text())
  })
  await page.goto("/")
  await expect(page).toHaveTitle("Rodzinna biblioteka")
  await page.getByLabel("Język interfejsu", { exact: true }).selectOption("en")
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
  const subject = await (
    await page.request.post("/api/subjects", {
      headers,
      data: { name: `Images ${info.project.name}` },
    })
  ).json()
  const topic = await (
    await page.request.post("/api/topics", {
      headers,
      data: { subject_id: subject.id, name: "Polski obrazki" },
    })
  ).json()
  const document = await (
    await page.request.post(`/api/topics/${topic.id}/youtube`, {
      headers,
      data: { url: "https://www.youtube.com/watch?v=6crPrHg2MZc" },
    })
  ).json()
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${document.job_id}`)).json())
          .status
    )
    .toBe("succeeded")
  const generated = await (
    await page.request.post("/api/generate", {
      headers,
      data: {
        topic_ids: [topic.id],
        mode: "flashcard",
        count: 1,
        idempotency_key: crypto.randomUUID(),
      },
    })
  ).json()
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${generated.id}`)).json())
          .status
    )
    .toBe("succeeded")
  let card = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  // The draft review entry also offers image editing; cancel retains uploaded files.
  await page.goto(`/#generation/${generated.id}`)
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  for (const slot of ["Question image", "Answer image"]) {
    const group = page.getByRole("group", { name: slot, exact: true })
    await group
      .getByLabel("Upload image", { exact: true })
      .setInputFiles({ name: "river.png", mimeType: "image/png", buffer: png })
    await expect(group.locator("img")).toHaveAttribute(
      "src",
      /\/api\/image-candidates\/.+\/preview$/
    )
    await expect
      .poll(async () =>
        group
          .locator("img")
          .evaluate(
            (img: HTMLImageElement) => img.complete && img.naturalWidth > 0
          )
      )
      .toBe(true)
  }
  const candidates = (
    await (
      await page.request.get(`/api/cards/${card.id}/image-candidates`)
    ).json()
  ).items
  expect(candidates).toHaveLength(2)
  expect(
    (
      await page.request.delete(`/api/image-candidates/${candidates[0].id}`)
    ).status()
  ).toBe(403)
  const anonymous = await browser.newContext()
  expect((await anonymous.request.get(candidates[0].url)).status()).toBe(401)
  const parent = await browser.newContext()
  const login = await parent.request.post("/api/auth/login", {
    headers: { Origin: headers.Origin },
    data: { username: "parent", password: "browser-parent-password" },
  })
  expect(login.ok()).toBe(true)
  expect((await parent.request.get(candidates[0].url)).status()).toBe(404)
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.reload()
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Use draft", exact: true })
  ).toHaveCount(2)
  for (const [slot, alt] of [
    ["Question image", "Nil: pytanie"],
    ["Answer image", "Nil: odpowiedź"],
  ]) {
    const group = page.getByRole("group", { name: slot, exact: true })
    await group.getByRole("button", { name: "Use draft", exact: true }).click()
    await group.getByLabel("Image description", { exact: true }).fill(alt)
    await page.keyboard.press("Tab")
    await expect(
      group.getByRole("button", { name: "Keep current image", exact: true })
    ).toBeFocused()
  }
  await page.getByRole("dialog").evaluate((element) => {
    element.scrollTop = 0
  })
  await page.screenshot({
    path: `/tmp/learning-images-editor-${info.project.name}.png`,
    fullPage: true,
  })
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  card = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  expect(card.version).toBe(2)
  expect(card.images.question.alt).toBe("Nil: pytanie")
  expect(card.images.answer.alt).toBe("Nil: odpowiedź")
  await page.request.post("/api/cards/save", {
    headers,
    data: { card_ids: [card.id] },
  })
  const session = await (
    await page.request.post("/api/study", {
      headers,
      data: { topic_ids: [topic.id], mode: "flashcard" },
    })
  ).json()
  expect(session.card.images).not.toHaveProperty("answer")
  const hiddenURL = `/api/study/${session.id}/cards/0/images/answer`
  expect((await page.request.get(hiddenURL)).status()).toBe(404)
  const requested: string[] = []
  page.on("request", (req) => {
    if (req.url().includes("/images/")) requested.push(req.url())
  })
  await page.goto(`/#study/${session.id}`)
  await expect(
    page.getByRole("img", { name: "Nil: pytanie", exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole("img", { name: "Nil: odpowiedź", exact: true })
  ).toHaveCount(0)
  expect(requested.some((url) => url.endsWith("/images/answer"))).toBe(false)
  await page.screenshot({
    path: `/tmp/learning-images-hidden-${info.project.name}.png`,
    fullPage: true,
  })
  const imageResponse = await page.request.get(session.card.images.question.url)
  expect(imageResponse.headers()["cache-control"]).toBe("no-store")
  expect(imageResponse.headers()["x-content-type-options"]).toBe("nosniff")
  // Regeneration can keep current images without including image fields in its strict candidate.
  await page.goto(`/#library/topic/${topic.id}/questions/${card.id}`)
  await page
    .getByRole("button", { name: "Regenerate question", exact: true })
    .click()
  await expect(
    page.getByText(`${card.question} (nowy wariant)`, { exact: true })
  ).toBeVisible()
  await page.getByRole("button", { name: "Apply variant", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  const regeneratedCard = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  expect(regeneratedCard.version).toBe(card.version + 1)
  expect(regeneratedCard.images).toEqual(card.images)
  // Changing both card images leaves the already-active study snapshot unchanged.
  await page.goto(`/#library/topic/${topic.id}/questions/${card.id}`)
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  const questionSlot = page.getByRole("group", {
    name: "Question image",
    exact: true,
  })
  await questionSlot.getByLabel("Upload image", { exact: true }).setInputFiles({
    name: "replacement.png",
    mimeType: "image/png",
    buffer: png,
  })
  await expect(questionSlot.locator("img")).toHaveAttribute(
    "src",
    /image-candidates/
  )
  await questionSlot.getByLabel("Image description").fill("Nowa ilustracja")
  await page
    .getByRole("group", { name: "Answer image", exact: true })
    .getByRole("button", { name: "Remove image", exact: true })
    .click()
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  expect(
    (await (await page.request.get(`/api/study/${session.id}`)).json()).card
  ).toEqual(session.card)
  await page.goto(`/#study/${session.id}`)
  await page.getByRole("button", { name: "Show answer", exact: true }).click()
  await expect(
    page.getByRole("img", { name: "Nil: odpowiedź", exact: true })
  ).toBeVisible()
  // BrowserAI asserts the illustration never reaches the explanation model.
  await page
    .getByRole("button", { name: "Explain simply", exact: true })
    .click()
  await expect(
    page.getByText("Нил — река, рядом с которой жили люди.", { exact: true })
  ).toBeVisible()
  await page.getByRole("button", { name: "Review again", exact: true }).click()
  await page
    .getByRole("button", { name: "Session result", exact: true })
    .click()
  await expect(
    page.getByRole("img", { name: "Nil: pytanie", exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole("img", { name: "Nil: odpowiedź", exact: true })
  ).toBeVisible()
  await page.screenshot({
    path: `/tmp/learning-images-history-${info.project.name}.png`,
    fullPage: true,
  })
  expect((await parent.request.get(`/api/study/${session.id}`)).status()).toBe(
    404
  )
  expect((await parent.request.get(hiddenURL)).status()).toBe(404)
  // Delete the live card, repeat still uses the original session image and alt.
  expect(
    (await page.request.delete(`/api/cards/${card.id}`, { headers })).ok()
  ).toBe(true)
  await page
    .getByRole("button", { name: "Review difficult cards", exact: true })
    .click()
  await expect(page).toHaveURL(/#study\/\d+$/)
  await expect(page).not.toHaveURL(new RegExp(`#study/${session.id}$`))
  const repeatId = Number(page.url().split("/").pop())
  expect(repeatId).not.toBe(session.id)
  await expect(
    page.getByRole("img", { name: "Nil: pytanie", exact: true })
  ).toBeVisible()
  await page.request.post("/api/study/delete", {
    headers,
    data: { session_ids: [session.id] },
  })
  await page.reload()
  await expect(
    page.getByRole("img", { name: "Nil: pytanie", exact: true })
  ).toBeVisible()
  const repeated = await (
    await page.request.get(`/api/study/${repeatId}`)
  ).json()
  expect(repeated.card.images.question.asset_id).toBe(
    session.card.images.question.asset_id
  )
  await page.getByRole("button", { name: "Show answer", exact: true }).click()
  await expect(
    page.getByRole("img", { name: "Nil: odpowiedź", exact: true })
  ).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth
    )
  ).toBe(true)
  const policyHeaders = (await page.request.get("/")).headers()
  const policy = policyHeaders["content-security-policy"]
    .split(";")
    .map((directive) => directive.trim())
  expect(policy).toContain("img-src 'self' data:")
  expect(policy).toContain("connect-src 'self'")
  expect(policy.filter((directive) => directive.includes("blob:"))).toEqual([
    "media-src 'self' blob:",
  ])
  expect(errors).toEqual([])
  await page.request.post("/api/study/delete", {
    headers,
    data: { session_ids: [repeatId] },
  })
  expect(
    (await page.request.get(repeated.card.images.question.url)).status()
  ).toBe(404)
  expect((await page.request.get(`/api/study/${repeatId}`)).status()).toBe(404)
  await anonymous.close()
  await parent.close()
})

test("explicit paid image review, timeout recovery and quiz answer privacy", async ({
  page,
}, info) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  page.on("console", (message) => {
    if (message.type() === "error" && !message.text().includes("status of"))
      errors.push(message.text())
  })
  await page.goto("/")
  await page.getByLabel("Język interfejsu", { exact: true }).selectOption("en")
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
  const subject = await (
    await page.request.post("/api/subjects", {
      headers,
      data: { name: `Paid images ${info.project.name}` },
    })
  ).json()
  const topic = await (
    await page.request.post("/api/topics", {
      headers,
      data: { subject_id: subject.id, name: "Quiz images" },
    })
  ).json()
  const document = await (
    await page.request.post(`/api/topics/${topic.id}/youtube`, {
      headers,
      data: { url: "https://www.youtube.com/watch?v=6crPrHg2MZc" },
    })
  ).json()
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${document.job_id}`)).json())
          .status
    )
    .toBe("succeeded")
  const generation = await (
    await page.request.post("/api/generate", {
      headers,
      data: {
        topic_ids: [topic.id],
        mode: "quiz",
        count: 1,
        idempotency_key: crypto.randomUUID(),
      },
    })
  ).json()
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${generation.id}`)).json())
          .status
    )
    .toBe("succeeded")
  const paidRequests: { url: string; body: unknown }[] = []
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      /generate-image|retry-image$/.test(request.url())
    )
      paidRequests.push({ url: request.url(), body: request.postDataJSON() })
  })
  await page.goto(`/#generation/${generation.id}`)
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  const question = page.getByRole("group", {
    name: "Question image",
    exact: true,
  })
  const answer = page.getByRole("group", { name: "Answer image", exact: true })
  await expect(
    question.getByLabel("Image prompt", { exact: true })
  ).toHaveValue(/bez tekstu/)
  await expect(
    question.getByRole("button", { name: "Generate image (paid)", exact: true })
  ).toBeEnabled()
  expect(paidRequests).toEqual([])
  for (const [locale, edit, generate, cancel] of [
    ["pl", "Edytuj pytanie", "Wygeneruj obrazek (płatnie)", "Anuluj"],
    ["ru", "Изменить карточку", "Сгенерировать картинку (платно)", "Отмена"],
    ["en", "Edit card", "Generate image (paid)", "Cancel"],
  ]) {
    await page
      .getByRole("button", { name: /^(Cancel|Anuluj|Отмена)$/, exact: true })
      .click()
    await page
      .getByLabel(/^(Interface language|Język interfejsu|Язык интерфейса)$/)
      .selectOption(locale)
    await page.getByRole("button", { name: edit, exact: true }).click()
    await expect(
      page.getByRole("button", { name: generate, exact: true })
    ).toHaveCount(2)
    await expect(
      page.getByRole("button", { name: cancel, exact: true })
    ).toBeVisible()
    expect(
      await page
        .getByRole("dialog")
        .evaluate((element) => element.scrollWidth <= element.clientWidth)
    ).toBe(true)
    await page
      .getByRole("button", { name: generate, exact: true })
      .first()
      .scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `/tmp/learning-images-paid-${locale}-${info.project.name}.png`,
      fullPage: true,
    })
    expect(paidRequests).toHaveLength(0)
  }
  await question
    .getByLabel("Image prompt", { exact: true })
    .fill(`timeout once ${info.project.name}`)
  await question
    .getByRole("button", { name: "Generate image (paid)", exact: true })
    .click()
  await expect(
    question.getByText(/The result and charge may be unknown/)
  ).toBeVisible()
  expect(paidRequests).toHaveLength(1)
  await question
    .getByText(/The result and charge may be unknown/)
    .scrollIntoViewIfNeeded()
  await page.screenshot({
    path: `/tmp/learning-images-timeout-${info.project.name}.png`,
    fullPage: true,
  })
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await page.reload()
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  await expect(
    question.getByRole("button", {
      name: "Try image generation again (paid)",
      exact: true,
    })
  ).toBeDisabled()
  expect(paidRequests).toHaveLength(1)
  await question
    .getByLabel("I understand another attempt may cost extra", { exact: true })
    .check()
  await question
    .getByRole("button", {
      name: "Try image generation again (paid)",
      exact: true,
    })
    .click()
  await expect(
    question.getByRole("button", { name: "Use draft", exact: true })
  ).toBeVisible()
  expect(paidRequests).toHaveLength(2)
  expect(paidRequests[1].body).toMatchObject({
    acknowledge_extra_cost: true,
    idempotency_key: expect.any(String),
  })
  expect(await question.locator("img").count()).toBe(0)
  await question.getByRole("button", { name: "Use draft", exact: true }).click()
  await expect(
    question.getByText("Created by AI", { exact: true })
  ).toBeVisible()
  await question
    .getByLabel("Image description", { exact: true })
    .fill("Quiz question illustration")
  await answer
    .getByLabel("Image prompt", { exact: true })
    .fill("provider denied")
  await answer
    .getByRole("button", { name: "Generate image (paid)", exact: true })
    .click()
  await expect(
    answer.getByRole("button", {
      name: "Try image generation again (paid)",
      exact: true,
    })
  ).toBeVisible()
  await expect(
    answer.getByText(
      "Provider rejected the image request. Check settings or explicitly retry.",
      { exact: true }
    )
  ).toBeVisible()
  await answer
    .getByRole("button", { name: "Discard image generation", exact: true })
    .click()
  // Provider refusal leaves normal upload available, including a long accessible alt.
  await answer
    .getByLabel("Upload image", { exact: true })
    .setInputFiles({ name: "river.png", mimeType: "image/png", buffer: png })
  await expect(answer.locator("img")).toHaveAttribute("src", /image-candidates/)
  const longAlt = "Długa odpowiedź ".repeat(30).slice(0, 500)
  await answer.getByLabel("Image description", { exact: true }).fill(longAlt)
  await expect(page.getByRole("dialog")).toBeVisible()
  expect(
    await page
      .getByRole("dialog")
      .evaluate((element) => element.scrollWidth <= element.clientWidth)
  ).toBe(true)
  await page.screenshot({
    path: `/tmp/learning-images-paid-editor-${info.project.name}.png`,
    fullPage: true,
  })
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
  await expect(page.getByRole("dialog")).toHaveCount(0)
  const card = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  expect(card.images.question.origin).toBe("generated")
  await page.request.post("/api/cards/save", {
    headers,
    data: { card_ids: [card.id] },
  })
  const session = await (
    await page.request.post("/api/study", {
      headers,
      data: { topic_ids: [topic.id], mode: "quiz" },
    })
  ).json()
  const before = JSON.stringify(session)
  expect(session.card.images).not.toHaveProperty("answer")
  expect(before).not.toContain(card.images.answer.asset_id)
  expect(before).not.toContain(longAlt)
  const hiddenURL = `/api/study/${session.id}/cards/0/images/answer`
  expect((await page.request.get(hiddenURL)).status()).toBe(404)
  const requests: string[] = []
  page.on("request", (request) => {
    if (request.url().includes(`/api/study/${session.id}/`))
      requests.push(request.url())
  })
  await page.goto(`/#study/${session.id}`)
  await expect(
    page.getByRole("img", { name: "Quiz question illustration", exact: true })
  ).toBeVisible()
  expect(requests.some((url) => url.endsWith("/images/answer"))).toBe(false)
  await expect(
    page.getByRole("img", { name: longAlt, exact: true })
  ).toHaveCount(0)
  await page.getByRole("button", { name: /Nil/ }).click()
  // Merely selecting an option must not reveal or prefetch the answer image.
  expect((await page.request.get(hiddenURL)).status()).toBe(404)
  expect(requests.some((url) => url.endsWith("/images/answer"))).toBe(false)
  await page.getByRole("button", { name: "Check answer", exact: true }).click()
  await expect(
    page.getByRole("img", { name: longAlt, exact: true })
  ).toBeVisible()
  expect((await page.request.get(hiddenURL)).ok()).toBe(true)
  expect(requests.some((url) => url.endsWith("/images/answer"))).toBe(true)
  await page.screenshot({
    path: `/tmp/learning-images-quiz-revealed-${info.project.name}.png`,
    fullPage: true,
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth
    )
  ).toBe(true)
  expect(errors).toEqual([])
})
