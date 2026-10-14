import { expect, test } from "@playwright/test"

test("preview survives reopen; local edits apply once and preserve active study", async ({
  page,
}, info) => {
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
      data: { name: `Regeneration ${info.project.name}` },
    })
  ).json()
  const topic = await (
    await page.request.post("/api/topics", {
      headers,
      data: { subject_id: subject.id, name: "Polski" },
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
  const original = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  await page.request.post("/api/cards/save", {
    headers,
    data: { card_ids: [original.id] },
  })
  const session = await (
    await page.request.post("/api/study", {
      headers,
      data: { topic_ids: [topic.id], mode: "quiz" },
    })
  ).json()
  await page.goto(`/#library/topic/${topic.id}/questions/${original.id}`)
  await expect(
    page.getByRole("button", { name: "Edit card", exact: true })
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Regenerate question", exact: true })
    .click()
  await expect(
    page.getByText(`${original.question} (nowy wariant)`, { exact: true })
  ).toBeVisible()
  const jobs = await (await page.request.get("/api/jobs")).json()
  const regenerate = jobs.find(
    (j: { kind: string; topic_ids: number[] }) =>
      j.kind === "regenerate" && j.topic_ids.includes(topic.id)
  )
  const unchanged = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  expect(unchanged.question).toBe(original.question)
  await page.getByRole("button", { name: "Close", exact: true }).click()
  await page.reload()
  await page
    .getByRole("button", { name: "Regenerate question", exact: true })
    .click()
  await expect(
    page.getByText(`${original.question} (nowy wariant)`, { exact: true })
  ).toBeVisible()
  expect(
    (await (await page.request.get("/api/jobs")).json()).filter(
      (j: { kind: string; topic_ids: number[] }) =>
        j.kind === "regenerate" && j.topic_ids.includes(topic.id)
    )
  ).toHaveLength(1)
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Edit card", exact: true })
    .click()
  await page
    .getByLabel("Question", { exact: true })
    .fill("Pytanie poprawione przez rodzica")
  await page
    .getByRole("button", { name: "Update candidate", exact: true })
    .click()
  await expect(
    page
      .getByRole("dialog")
      .getByText("Pytanie poprawione przez rodzica", { exact: true })
  ).toBeVisible()
  await page.screenshot({
    path: `/tmp/learning-regeneration-${info.project.name}.png`,
    fullPage: true,
  })
  await page.getByRole("button", { name: "Apply variant", exact: true }).click()
  await expect(
    page
      .getByRole("main")
      .getByText("Pytanie poprawione przez rodzica", { exact: true })
  ).toBeVisible()
  const current = (
    await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
  )[0]
  expect(current.version).toBe(original.version + 1) // Apply exactly once; saving a draft does not change its version.
  expect(current.status).toBe("saved")
  const frozen = await (
    await page.request.get(`/api/study/${session.id}`)
  ).json()
  expect(frozen.card).toEqual(session.card)
  expect(
    (await (await page.request.get(`/api/jobs/${regenerate.id}`)).json()).result
      .applied_version
  ).toBe(current.version)
  await page
    .getByRole("button", { name: "Regenerate question", exact: true })
    .click()
  await expect(
    page.getByText("Pytanie poprawione przez rodzica (nowy wariant)", {
      exact: true,
    })
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Discard variant", exact: true })
    .click()
  expect(
    (
      await (await page.request.get(`/api/cards?topic_id=${topic.id}`)).json()
    )[0].question
  ).toBe("Pytanie poprawione przez rodzica")
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth
    )
  ).toBe(true)
})
