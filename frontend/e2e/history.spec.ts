import { expect, test } from "@playwright/test"

test("select, cancel and delete personal history without removing library materials", async ({
  page,
}, testInfo) => {
  const errors: string[] = []
  page.on("pageerror", (error) => errors.push(error.message))
  await page.goto("/")
  await page.getByLabel("Login", { exact: true }).fill("child")
  await page.getByLabel("Hasło", { exact: true }).fill("browser-child-password")
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click()
  await expect(
    page.getByRole("link", { name: "Biblioteka", exact: true })
  ).toBeVisible()
  // The login screen intentionally probes /auth/me before authentication (401).
  // Collect resource errors for the authenticated history flow under test.
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning")
      errors.push(message.text())
  })
  const auth = await (await page.request.get("/api/auth/me")).json()
  const headers = {
    Origin: new URL(page.url()).origin,
    "X-CSRF-Token": auth.csrf_token,
  }
  async function post(path: string, data: unknown) {
    const response = await page.request.post(`/api${path}`, { headers, data })
    expect(response.ok(), await response.text()).toBe(true)
    return response.json()
  }
  const name = `History cleanup ${testInfo.project.name}`
  const subject = await post("/subjects", { name })
  const topic = await post("/topics", { subject_id: subject.id, name })
  const document = await post(`/topics/${topic.id}/youtube`, {
    url: "https://www.youtube.com/watch?v=6crPrHg2MZc",
  })
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${document.job_id}`)).json())
          .status
    )
    .toBe("succeeded")
  const generation = await post("/generate", {
    topic_ids: [topic.id],
    mode: "quiz",
    count: 1,
  })
  await expect
    .poll(
      async () =>
        (await (await page.request.get(`/api/jobs/${generation.id}`)).json())
          .status
    )
    .toBe("succeeded")
  const cards = await (
    await page.request.get(`/api/cards?job_id=${generation.id}`)
  ).json()
  await post("/cards/save", {
    card_ids: cards.map((c: { id: number }) => c.id),
  })
  const completed = await post("/study", {
    topic_ids: [topic.id],
    mode: "quiz",
  })
  await post(`/study/${completed.id}/answer`, {
    position: 0,
    choice: 0,
    idempotency_key: `bulk-${completed.id}`,
  })
  const active = await post("/study", {
    topic_ids: [topic.id],
    mode: "flashcard",
  })
  const retained = await post("/study", { topic_ids: [topic.id], mode: "quiz" })
  const documentsBefore = await (
    await page.request.get(`/api/topics/${topic.id}/documents`)
  ).json()
  const download = `/api/documents/${document.id}/download`
  const bytesBefore = await (await page.request.get(download)).body()
  await page.goto("/#history")
  await expect(page).toHaveURL(/#history$/)
  await expect(page).toHaveTitle(/.+/)
  await page.getByRole("button", { name: "Wybierz sesje", exact: true }).click()
  await page
    .getByRole("checkbox", {
      name: `Wybierz sesję #${completed.id}`,
      exact: true,
    })
    .check()
  await page
    .getByRole("checkbox", { name: `Wybierz sesję #${active.id}`, exact: true })
    .check()
  await page
    .getByRole("button", { name: "Usuń wybrane (2)", exact: true })
    .click()
  const dialog = page.getByRole("dialog")
  await expect(
    dialog.getByText("Sesje do usunięcia: 2.", { exact: true })
  ).toBeVisible()
  await expect(
    dialog.getByRole("button", { name: "Anuluj", exact: true })
  ).toBeFocused()
  await page.screenshot({
    path: `/tmp/learning-history-${testInfo.project.name}.png`,
    fullPage: false,
    animations: "disabled",
  })
  await dialog.getByRole("button", { name: "Anuluj", exact: true }).click()
  expect((await page.request.get(`/api/study/${completed.id}`)).status()).toBe(
    200
  )
  await expect(
    page.getByRole("checkbox", {
      name: `Wybierz sesję #${completed.id}`,
      exact: true,
    })
  ).toBeChecked()
  await page
    .getByRole("button", { name: "Usuń wybrane (2)", exact: true })
    .click()
  await dialog.getByRole("button", { name: "Usuń", exact: true }).click()
  await expect(page.getByRole("status")).toContainText("Usunięte sesje: 2.")
  expect((await page.request.get(`/api/study/${completed.id}`)).status()).toBe(
    404
  )
  expect((await page.request.get(`/api/study/${active.id}`)).status()).toBe(404)
  expect((await page.request.get(`/api/study/${retained.id}`)).status()).toBe(
    200
  )
  expect(
    await (await page.request.get(`/api/topics/${topic.id}/documents`)).json()
  ).toEqual(documentsBefore)
  expect(await (await page.request.get(download)).body()).toEqual(bytesBefore)
  expect(
    await (await page.request.get(`/api/cards?job_id=${generation.id}`)).json()
  ).toEqual(cards.map((c: { status: string }) => ({ ...c, status: "saved" })))
  await page.reload()
  await page.getByRole("button", { name: "Wybierz sesje", exact: true }).click()
  await expect(
    page.getByRole("checkbox", {
      name: `Wybierz sesję #${completed.id}`,
      exact: true,
    })
  ).toHaveCount(0)
  await expect(
    page.getByRole("checkbox", {
      name: `Wybierz sesję #${retained.id}`,
      exact: true,
    })
  ).not.toBeChecked()
  await page
    .getByRole("button", { name: "Wybierz wszystkie widoczne", exact: true })
    .click()
  await expect(
    page.getByRole("checkbox", {
      name: `Wybierz sesję #${retained.id}`,
      exact: true,
    })
  ).toBeChecked()
  await page
    .getByRole("button", { name: "Odznacz wszystkie", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "Usuń wybrane (0)", exact: true })
  ).toBeDisabled()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1
    )
  ).toBe(true)
  expect(errors).toEqual([])
})
