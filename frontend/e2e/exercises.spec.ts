import { expect, test } from "@playwright/test"

const methods = {
  written: "Short written answer",
  gap: "Fill in the gaps",
  ending: "Word endings",
  matching: "Matching pairs",
  ordering: "Sentence ordering",
}
for (const [kind, label] of Object.entries(methods))
  test(`${kind} preparation, complete input, immutable resume and result`, async ({
    page,
  }, info) => {
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
    const subject = await (
      await page.request.post("/api/subjects", {
        headers,
        data: { name: `Exercises ${kind} ${info.project.name}` },
      })
    ).json()
    const topic = await (
      await page.request.post("/api/topics", {
        headers,
        data: { subject_id: subject.id, name: `Polski ${kind}` },
      })
    ).json()
    await page.goto(`/#library/topic/${topic.id}/materials`)
    await page
      .getByLabel("YouTube link", { exact: true })
      .fill("https://www.youtube.com/watch?v=6crPrHg2MZc")
    await page.getByRole("button", { name: "Add YouTube", exact: true }).click()
    await expect(
      page.getByText("Captions: pl · 1 segments", { exact: false })
    ).toBeVisible()
    await page.goto(`/#library/topic/${topic.id}`)
    await page.getByRole("combobox", { name: "Practice method" }).click()
    await page.getByRole("option", { name: new RegExp(label) }).click()
    await page
      .getByRole("button", { name: "Prepare exercises", exact: true })
      .click()
    await expect(page).toHaveURL(new RegExp(`/create/${kind}$`))
    await page.getByLabel("How many questions?").fill("1")
    await page
      .getByRole("button", { name: "Create questions", exact: true })
      .click()
    await expect(
      page.getByRole("heading", { name: "Review new questions" })
    ).toBeVisible()
    await page.getByRole("button", { name: "Select all", exact: true }).click()
    await page
      .getByRole("button", { name: "Save selected (1)", exact: true })
      .click()
    await page.getByRole("button", { name: "Go to study", exact: true }).click()
    await page.getByRole("combobox", { name: "Practice method" }).click()
    await page.getByRole("option", { name: new RegExp(label) }).click()
    await page
      .getByRole("button", { name: "Start studying", exact: true })
      .click()
    await expect(page).toHaveURL(/#study\/\d+$/)
    const before = await (
      await page.request.get(`/api/study/${page.url().split("/").pop()}`)
    ).json()
    await page.reload()
    const after = await (
      await page.request.get(`/api/study/${page.url().split("/").pop()}`)
    ).json()
    expect(after.card).toEqual(before.card)
    const check = page.getByRole("button", {
      name: "Check answer",
      exact: true,
    })
    await expect(check).toBeDisabled()
    if (kind === "written")
      await page.getByLabel("Your answer", { exact: true }).fill("Nil")
    if (kind === "gap") {
      await page.getByLabel("Gap 1", { exact: true }).fill("rzeka")
      await expect(check).toBeDisabled()
      await page.getByLabel("Gap 2", { exact: true }).fill("Egipcie")
    }
    if (kind === "ending")
      await page.getByLabel("Gap 1", { exact: true }).fill("a")
    if (kind === "matching") {
      await page.getByRole("button", { name: "Nil", exact: true }).click()
      await page.getByRole("button", { name: "rzeka", exact: true }).click()
      await expect(check).toBeDisabled()
      await page.getByRole("button", { name: "Egipt", exact: true }).click()
      await page.getByRole("button", { name: "kraj", exact: true }).click()
    }
    if (kind === "ordering")
      for (const word of ["Nil", "to", "rzeka"])
        await page.getByRole("button", { name: word, exact: true }).click()
    await page.screenshot({
      path: `/tmp/learning-${kind}-input-${info.project.name}.png`,
      fullPage: true,
    })
    await check.click()
    await expect(
      page.locator(".answer-content").getByText("Correct!", { exact: true })
    ).toBeVisible()
    await page
      .getByRole("button", { name: "Session result", exact: true })
      .click()
    await expect(
      page.getByText("Another step forward", { exact: true })
    ).toBeVisible()
    await page.screenshot({
      path: `/tmp/learning-${kind}-${info.project.name}.png`,
      fullPage: true,
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
  })
