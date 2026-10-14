import { expect, test, type Page } from "@playwright/test"

const video = "https://www.youtube.com/watch?v=6crPrHg2MZc"
const photo = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAIAAACRXR/mAAAAZ0lEQVR4nM3OQQEAIACEMKR/57OAf1mCnW30SJIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIkSZIk+TvwdgEBKANhs+2fZgAAAABJRU5ErkJggg==",
  "base64"
)

async function login(page: Page, username = "child") {
  await page.goto("/")
  await page.getByLabel("Login", { exact: true }).fill(username)
  await page
    .getByLabel("Hasło", { exact: true })
    .fill(`browser-${username}-password`)
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click()
  await page
    .getByRole("combobox", { name: "Język interfejsu" })
    .selectOption("en")
  await expect(
    page.getByRole("link", { name: "Library", exact: true })
  ).toBeVisible()
}

async function createTopic(page: Page, name: string) {
  await page.getByRole("button", { name: "Add subject", exact: true }).click()
  await page.getByLabel("Name", { exact: true }).fill(`History ${name}`)
  await page.getByRole("button", { name: "Save", exact: true }).click()
  await page.getByRole("button", { name: "Add topic", exact: true }).click()
  await page.getByLabel("Name", { exact: true }).fill(name)
  await page.getByRole("button", { name: "Save", exact: true }).click()
  await expect(page).toHaveURL(/#library\/topic\/\d+$/)
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible()
  return page.url().split("#")[1]
}

async function addVideo(page: Page) {
  await page.getByLabel("YouTube link", { exact: true }).fill(video)
  await page.getByRole("button", { name: "Add YouTube", exact: true }).click()
  await expect(
    page.getByText("Captions: pl · 1 segments", { exact: false })
  ).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Download saved captions" })
  ).toBeVisible()
}

async function generate(page: Page, topic: string, count = 2) {
  await page.goto(`/#${topic}/create`)
  await expect(
    page.getByText("Questions will use the source materials’ language.")
  ).toBeVisible()
  await expect(
    page.getByLabel("Translate questions into another language")
  ).toHaveCount(0)
  await page.getByLabel("How many questions?").fill(String(count))
  await page
    .getByRole("button", { name: "Create questions", exact: true })
    .click()
  await expect(
    page.getByRole("heading", { name: "Review new questions" })
  ).toBeVisible()
  await expect(page.getByRole("checkbox").first()).toBeVisible()
  return page.url()
}

async function saveDrafts(page: Page, count = 2) {
  await page.getByRole("button", { name: "Select all", exact: true }).click()
  await page
    .getByRole("button", { name: `Save selected (${count})`, exact: true })
    .click()
  await page.getByRole("button", { name: "Go to study", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Start studying", exact: true })
  ).toBeEnabled()
}

function pdf(text: string) {
  const stream = `BT /F1 12 Tf 50 750 Td (${text}) Tj ET`
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
  ]
  let content = "%PDF-1.4\n"
  const offsets = [0]
  objects.forEach((object, index) => {
    offsets.push(content.length)
    content += `${index + 1} 0 obj\n${object}\nendobj\n`
  })
  const xref = content.length
  content += `xref\n0 6\n0000000000 65535 f \n${offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n `)
    .join("\n")}\ntrailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`
  return Buffer.from(content)
}

const browserErrors = new WeakMap<Page, string[]>()

test.beforeEach(async ({ page }) => {
  const errors: string[] = []
  browserErrors.set(page, errors)
  page.on("pageerror", (error) => errors.push(error.message))
})

test.afterEach(async ({ page }) => {
  expect(browserErrors.get(page), "uncaught browser errors").toEqual([])
})

test("login, three interface languages, persistence and logout", async ({
  page,
}) => {
  const response = await page.goto("/")
  expect(response?.headers()["x-robots-tag"]).toBe("noindex, nofollow")
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute(
    "content",
    "noindex, nofollow"
  )
  await expect(page).toHaveTitle(/.+/)
  await page.getByLabel("Login", { exact: true }).fill("child")
  await page.getByLabel("Hasło", { exact: true }).fill("incorrect-password")
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click()
  await expect(page.getByRole("alert")).toBeVisible()
  await page.getByLabel("Hasło", { exact: true }).fill("browser-child-password")
  await page.getByRole("button", { name: "Zaloguj się", exact: true }).click()
  const language = page.getByRole("combobox", { name: "Język interfejsu" })
  await language.selectOption("ru")
  await expect(
    page.getByRole("link", { name: "Библиотека", exact: true })
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Язык интерфейса" })
    .selectOption("en")
  await page.reload()
  await expect(
    page.getByRole("link", { name: "Library", exact: true })
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Interface language" })
    .selectOption("pl")
  await expect(
    page.getByRole("link", { name: "Biblioteka", exact: true })
  ).toBeVisible()
  await page.getByRole("button", { name: "Wyloguj się", exact: true }).click()
  await expect(
    page.getByRole("button", { name: "Zaloguj się", exact: true })
  ).toBeVisible()
  expect((await page.request.get("/api/subjects")).status()).toBe(401)
})

test("materials, original captions, drafts, both study modes and explanations", async ({
  page,
}, testInfo) => {
  await login(page)
  const topic = await createTopic(page, `Polska ${testInfo.project.name}`)
  await expect(
    page.getByRole("button", { name: "Prepare exercises", exact: true })
  ).toBeEnabled()
  await page.getByRole("link", { name: "Materials", exact: true }).click()
  const files = page.getByLabel("Choose PDF or photos", { exact: true })
  await files.setInputFiles({
    name: "invalid.pdf",
    mimeType: "application/pdf",
    buffer: Buffer.from("invalid"),
  })
  await page
    .getByRole("button", { name: "Upload files (1)", exact: true })
    .click()
  await expect(page.getByRole("alert")).toBeVisible()
  const lesson = {
    name: "lesson.pdf",
    mimeType: "application/pdf",
    buffer: pdf("The Nile is a river in Egypt."),
  }
  await files.setInputFiles(lesson)
  await page
    .getByRole("button", { name: "Upload files (1)", exact: true })
    .click()
  await expect(
    page
      .locator(".document-row")
      .filter({ hasText: "lesson.pdf" })
      .getByText("Ready", { exact: true })
  ).toBeVisible()
  await files.setInputFiles(lesson)
  await page
    .getByRole("button", { name: "Upload files (1)", exact: true })
    .click()
  await expect(
    page.getByText("This file is already saved in this topic", { exact: true })
  ).toBeVisible()
  await expect(page.locator(".document-row")).toHaveCount(1)
  await addVideo(page)
  const download = await page.request.get(
    (await page
      .getByRole("link", { name: "Download saved captions" })
      .getAttribute("href")) || ""
  )
  expect(await download.json()).toMatchObject({
    language: "pl",
    segments: [
      { text: "Nil to rzeka w Egipcie.", start: 5.894, duration: 3.356 },
    ],
  })
  await addVideo(page)
  await expect(
    page.getByText("This video is already saved in this topic", { exact: true })
  ).toBeVisible()
  await expect(page.locator(".document-row")).toHaveCount(2)
  const drafts = await generate(page, topic)
  await page.reload()
  await expect(
    page.getByRole("heading", { name: "Review new questions" })
  ).toBeVisible()
  await saveDrafts(page)
  await page
    .getByRole("button", { name: "Start studying", exact: true })
    .click()
  await expect(page).toHaveURL(/#study\/\d+$/)
  const session = page.url()
  await expect(
    page.getByRole("button", { name: "Explain simply", exact: true })
  ).toBeDisabled()
  await page.getByRole("button", { name: "Show answer", exact: true }).click()
  await expect(page.getByText("Nil", { exact: true })).toBeVisible()
  await page
    .getByRole("button", { name: "Explain simply", exact: true })
    .click()
  await expect(
    page.getByText("Нил — река, рядом с которой жили люди.", { exact: true })
  ).toBeVisible()
  await page.getByLabel("Your follow-up question").fill("Dlaczego?")
  await page.getByRole("button", { name: "Ask", exact: true }).click()
  await expect(page.getByText("Dlaczego?", { exact: true })).toBeVisible()
  await page.getByRole("button", { name: "I remember", exact: true }).click()
  await page.getByRole("button", { name: "Next card", exact: true }).click()
  await page.reload()
  await expect(
    page.getByRole("link", { name: "Back to topic", exact: true })
  ).toHaveAttribute("href", `#${topic}`)
  await page.getByRole("link", { name: "History", exact: true }).click()
  await page.locator(`a[href="#${session.split("#")[1]}"]`).click()
  await page.getByRole("button", { name: "Show answer", exact: true }).click()
  await page.getByRole("button", { name: "Review again", exact: true }).click()
  await page
    .getByRole("button", { name: "Session result", exact: true })
    .click()
  await expect(
    page.getByText("Another step forward", { exact: true })
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Review difficult cards", exact: true })
    .click()
  await expect(
    page.getByRole("button", { name: "Show answer", exact: true })
  ).toBeVisible()
  await page.getByRole("link", { name: "Back to topic", exact: true }).click()
  await selectPractice(page, "Multiple choice")
  await page
    .getByRole("button", { name: "Start studying", exact: true })
    .click()
  for (let index = 0; index < 2; index++) {
    await page
      .locator(".quiz-option")
      .getByText("Wisła", { exact: true })
      .click()
    await page
      .getByRole("button", { name: "Check answer", exact: true })
      .click()
    await expect(page.locator(".quiz-option.incorrect")).toHaveClass(
      /text-destructive/
    )
    await expect(page.locator(".quiz-option.correct")).toHaveClass(
      /text-emerald/
    )
    await expect(
      page.getByText("Incorrect. The correct answer is:", { exact: true })
    ).toBeVisible()
    if (!index)
      await page.screenshot({
        path: testInfo.outputPath("incorrect-answer.png"),
        fullPage: true,
      })
    await page
      .getByRole("button", {
        name: index ? "Session result" : "Next card",
        exact: true,
      })
      .click()
  }
  await expect(
    page.getByText("Another step forward", { exact: true })
  ).toBeVisible()
  await page
    .getByRole("link", { name: "Back to topic", exact: true })
    .last()
    .click()
  await expect(page).toHaveURL(new RegExp(`#${topic}$`))
  await page.getByRole("link", { name: "Questions", exact: true }).click()
  await expect(
    page.getByRole("link", { name: /Jak nazywa się rzeka/ })
  ).toHaveCount(2)
  await page.goto(drafts)
  await expect(page.getByRole("checkbox")).toHaveCount(0)
})

test("edit questions, append materials and keep another user's history private", async ({
  page,
}, testInfo) => {
  await login(page)
  const topic = await createTopic(page, `Append ${testInfo.project.name}`)
  await page.getByRole("button", { name: "Rename", exact: true }).click()
  await page
    .getByLabel("Name", { exact: true })
    .fill(`Renamed ${testInfo.project.name}`)
  await page.getByRole("button", { name: "Save", exact: true }).click()
  await expect(
    page.getByRole("heading", {
      name: `Renamed ${testInfo.project.name}`,
      exact: true,
    })
  ).toBeVisible()
  await page.getByRole("link", { name: "Materials", exact: true }).click()
  await addVideo(page)
  await generate(page, topic, 1)
  await saveDrafts(page, 1)
  await page.getByRole("link", { name: "Questions", exact: true }).click()
  await page.getByRole("link", { name: /Jak nazywa się rzeka/ }).click()
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  await page
    .getByLabel("Question", { exact: true })
    .fill("Jak nazywa się rzeka w Egipcie?")
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
  await page.reload()
  await expect(
    page.getByText("Jak nazywa się rzeka w Egipcie?", { exact: true })
  ).toBeVisible()
  const timestamp = page.locator('.sources a[href*="youtube.com"]')
  await expect(timestamp).toHaveAttribute("href", /[?&]t=5/)
  await page.goto(`/#${topic}/materials`)
  await page.getByLabel("Choose PDF or photos", { exact: true }).setInputFiles({
    name: "extra.pdf",
    mimeType: "application/pdf",
    buffer: pdf("Additional material about Egyptian boats."),
  })
  await page
    .getByRole("button", { name: "Upload files (1)", exact: true })
    .click()
  await expect(
    page
      .locator(".document-row")
      .filter({ hasText: "extra.pdf" })
      .getByText("Ready", { exact: true })
  ).toBeVisible()
  await generate(page, topic, 1)
  await saveDrafts(page, 1)
  await page.getByRole("link", { name: "Questions", exact: true }).click()
  await expect(
    page.getByRole("link", { name: /Jak nazywa się rzeka/ })
  ).toHaveCount(2)
  await page.screenshot({
    path: testInfo.outputPath("topic-questions.png"),
    fullPage: true,
    animations: "disabled",
  })
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1
    )
  ).toBe(true)
  await page.getByRole("button", { name: "Sign out", exact: true }).click()
  // Interface preference persists on this device, independently of who signs in.
  await page.getByLabel("Username", { exact: true }).fill("parent")
  await page
    .getByLabel("Password", { exact: true })
    .fill("browser-parent-password")
  await page.getByRole("button", { name: "Sign in", exact: true }).click()
  await page.goto(`/#${topic}`)
  await expect(
    page.getByRole("button", { name: "Start studying", exact: true })
  ).toBeEnabled()
  await page.getByRole("link", { name: "History", exact: true }).click()
  await expect(
    page.getByText("Your first session awaits", { exact: true })
  ).toBeVisible()
  expect(await (await page.request.get("/api/study")).json()).toEqual([])
})

test("photos and selected topics include only the chosen learning material", async ({
  page,
}, testInfo) => {
  await login(page)
  const names = ["First", "Second", "Excluded"].map(
    (name) => `${name} ${testInfo.project.name}`
  )
  const first = await createTopic(page, names[0])
  await page.getByRole("link", { name: "Materials", exact: true }).click()
  await addVideo(page)
  await generate(page, first, 1)
  await saveDrafts(page, 1)
  await page.getByRole("link", { name: "Back to topics", exact: true }).click()
  const subject = page.url()
  const topics = [Number(first.split("/").pop())]
  for (const name of names.slice(1)) {
    await page.getByRole("button", { name: "Add topic", exact: true }).click()
    await page.getByLabel("Name", { exact: true }).fill(name)
    await page.getByRole("button", { name: "Save", exact: true }).click()
    await expect(page.getByRole("heading", { name, exact: true })).toBeVisible()
    const topic = page.url().split("#")[1]
    topics.push(Number(topic.split("/").pop()))
    await page.getByRole("link", { name: "Materials", exact: true }).click()
    await page
      .getByLabel("Choose PDF or photos", { exact: true })
      .setInputFiles({
        name: "page.png",
        mimeType: "image/png",
        buffer: photo,
      })
    await page
      .getByRole("button", { name: "Upload files (1)", exact: true })
      .click()
    await expect(
      page.locator(".document-row").getByText("Ready", { exact: true })
    ).toBeVisible()
    const fileUrl = await page
      .getByRole("link", { name: "page.png", exact: true })
      .getAttribute("href")
    expect(await (await page.request.get(fileUrl!)).body()).toEqual(photo)
    await generate(page, topic, 1)
    await saveDrafts(page, 1)
    await page.goto(subject)
  }
  await page
    .getByRole("button", { name: "Rename subject", exact: true })
    .click()
  await page
    .getByLabel("Name", { exact: true })
    .fill(`Selected topics ${testInfo.project.name}`)
  await page.getByRole("button", { name: "Save", exact: true }).click()
  await expect(
    page.getByRole("heading", {
      name: `Selected topics ${testInfo.project.name}`,
      exact: true,
    })
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Choose topics to review", exact: true })
    .click()
  await page.getByRole("checkbox", { name: names[0], exact: true }).check()
  await page.getByRole("checkbox", { name: names[1], exact: true }).check()
  await expect(
    page.getByRole("checkbox", { name: names[2], exact: true })
  ).not.toBeChecked()
  await page
    .getByRole("button", { name: "Start studying", exact: true })
    .click()
  await expect(page).toHaveURL(/#study\/\d+$/)
  const id = page.url().split("/").pop()
  const session = await (await page.request.get(`/api/study/${id}`)).json()
  expect(session.topic_ids.toSorted()).toEqual(topics.slice(0, 2).toSorted())
  expect(session.count).toBe(2)
  expect(session.topic_names.toSorted()).toEqual(names.slice(0, 2).toSorted())
  await expect(
    page.getByRole("link", { name: "Return to library", exact: true })
  ).toHaveAttribute("href", "#library")
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1
    )
  ).toBe(true)
})

test("multiple answers, deletion confirmations, reupload and preserved history", async ({
  page,
}, testInfo) => {
  await login(page)
  const name = `Cleanup ${testInfo.project.name}`
  const topic = await createTopic(page, name)
  await page.goto(`/#${topic}/materials`)
  await addVideo(page)
  await generate(page, topic, 1)
  await page.getByRole("button", { name: "Edit card", exact: true }).click()
  await page
    .getByLabel("Question", { exact: true })
    .fill("Select all translations of table")
  await page.getByLabel("Answer", { exact: true }).fill("stół; tabela")
  await page.getByLabel("Option 1", { exact: true }).fill("stół")
  await page.getByLabel("Option 2", { exact: true }).fill("tabela")
  await page.getByLabel("Option 3", { exact: true }).fill("krzesło")
  await page
    .getByRole("checkbox", { name: "Correct option 2", exact: true })
    .check()
  await page.getByRole("button", { name: "Save changes", exact: true }).click()
  await saveDrafts(page, 1)
  await selectPractice(page, "Multiple choice")
  await page
    .getByRole("button", { name: "Start studying", exact: true })
    .click()
  await expect(
    page.getByText("Select all correct answers", { exact: true })
  ).toBeVisible()
  await page.getByRole("checkbox", { name: "stół", exact: true }).check()
  await page.getByRole("checkbox", { name: "krzesło", exact: true }).check()
  await page.getByRole("button", { name: "Check answer", exact: true }).click()
  await expect(
    page.getByText("Missed correct answer", { exact: true })
  ).toBeVisible()
  await expect(
    page.getByRole("checkbox", { name: "krzesło" }).locator("..")
  ).toHaveClass(/incorrect/)
  await expect(
    page.getByText("Questions saved in topics", { exact: true })
  ).toBeHidden()
  await page.screenshot({
    path: `/tmp/learning-multiple-${testInfo.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  })
  await page
    .getByRole("button", { name: "Session result", exact: true })
    .click()
  await expect(
    page.getByText(/^Your answer: (stół; krzesło|krzesło; stół)$/)
  ).toBeVisible()
  const sessionURL = page.url()
  await page
    .getByRole("link", { name: "Back to topic", exact: true })
    .first()
    .click()
  await page.goto(`/#${topic}/materials`)
  await page
    .getByRole("button", { name: "Delete material", exact: true })
    .click()
  await expect(
    page.getByText("Materials to delete: 1. Questions to delete: 1.", {
      exact: true,
    })
  ).toBeVisible()
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(
    page.getByRole("link", { name: "Download saved captions" })
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Delete material", exact: true })
    .click()
  await page.getByRole("button", { name: "Delete", exact: true }).click()
  await expect(
    page.getByRole("link", { name: "Download saved captions" })
  ).toHaveCount(0)
  await page.goto(sessionURL)
  await expect(
    page.getByText(/^Your answer: (stół; krzesło|krzesło; stół)$/)
  ).toBeVisible()
  await expect(page.getByText(/Material deleted/)).toBeVisible()
  await page.goto(`/#${topic}/questions`)
  await expect(
    page.getByText("No questions yet", { exact: true })
  ).toBeVisible()
  await page.goto(`/#${topic}/materials`)
  await addVideo(page)
  await generate(page, topic, 1)
  await saveDrafts(page, 1)
  await page.goto(`/#${topic}/questions`)
  await page
    .getByRole("button", { name: "Delete question", exact: true })
    .click()
  await page.getByRole("button", { name: "Delete", exact: true }).click()
  await expect(
    page.getByText("No questions yet", { exact: true })
  ).toBeVisible()
  await page.goto(`/#${topic}`)
  await page.getByRole("button", { name: "Delete topic", exact: true }).click()
  await expect(
    page.getByText("Questions saved in topics", { exact: true })
  ).toBeHidden()
  await page.screenshot({
    path: `/tmp/learning-delete-${testInfo.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  })
  await page.getByRole("button", { name: "Delete", exact: true }).click()
  await expect(page).toHaveURL(/#library\/subject\/\d+$/)
  await expect(page.getByRole("link", { name, exact: true })).toHaveCount(0)
  await page.goto(sessionURL)
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Return to library", exact: true }).first()
  ).toHaveAttribute("href", "#library")
  await expect(
    page.getByText(/^Your answer: (stół; krzesło|krzesło; stół)$/)
  ).toBeVisible()
  await page
    .getByRole("button", { name: "Review difficult cards", exact: true })
    .click()
  await page.getByRole("checkbox", { name: "stół", exact: true }).check()
  await page.getByRole("checkbox", { name: "tabela", exact: true }).check()
  await page.getByRole("button", { name: "Check answer", exact: true }).click()
  await expect(page.getByText("Correct!", { exact: true })).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1
    )
  ).toBe(true)
})

test("delete a whole subject, keep private originals protected and preserve history", async ({
  page,
  browser,
}, testInfo) => {
  await login(page)
  const name = `Subject cleanup ${testInfo.project.name}`
  const topic = await createTopic(page, name)
  const topicId = topic.split("/").pop()
  const topicData = await (
    await page.request.get(`/api/topics/${topicId}`)
  ).json()
  const subjectRoute = `/#library/subject/${topicData.subject_id}`
  await page.goto(`/#${topic}/materials`)
  await page.getByLabel("Choose PDF or photos", { exact: true }).setInputFiles({
    name: "private.pdf",
    mimeType: "application/pdf",
    buffer: pdf("Original private lesson for browser QA"),
  })
  await page
    .getByRole("button", { name: "Upload files (1)", exact: true })
    .click()
  await expect(
    page.getByRole("link", { name: "private.pdf", exact: true })
  ).toBeVisible()
  const pdfDownload = await page
    .getByRole("link", { name: "private.pdf", exact: true })
    .getAttribute("href")
  await addVideo(page)
  await generate(page, topic, 1)
  await saveDrafts(page, 1)
  await selectPractice(page, "Multiple choice")
  await page
    .getByRole("button", { name: "Start studying", exact: true })
    .click()
  await page.getByRole("button", { name: /Wisła/ }).click()
  await page.getByRole("button", { name: "Check answer", exact: true }).click()
  await page
    .getByRole("button", { name: "Session result", exact: true })
    .click()
  await expect(
    page.getByText("Session completed. Your result is saved in history.")
  ).toBeVisible()
  const sessionURL = page.url()
  const anonymous = await browser.newContext()
  expect(
    (
      await anonymous.request.get(new URL(pdfDownload!, page.url()).href)
    ).status()
  ).toBe(401)
  const docs = await (
    await page.request.get(`/api/topics/${topicId}/documents`)
  ).json()
  const captions = docs.find((doc: { source_url?: string }) => !!doc.source_url)
  expect(
    (
      await anonymous.request.get(
        new URL(`/api/documents/${captions.id}/download`, page.url()).href
      )
    ).status()
  ).toBe(401)
  await anonymous.close()
  expect((await page.request.get(pdfDownload!)).status()).toBe(200)
  await page.goto(subjectRoute)
  await page.getByRole("button", { name: "Add topic", exact: true }).click()
  await page.getByLabel("Name", { exact: true }).fill("Empty child topic")
  await page.getByRole("button", { name: "Save", exact: true }).click()
  await expect(page).toHaveURL(/#library\/topic\/\d+$/)
  await page.goto(subjectRoute)
  await page
    .getByRole("button", { name: "Delete subject", exact: true })
    .click()
  await expect(
    page.getByText("Topics to delete: 2.", { exact: true })
  ).toBeVisible()
  await expect(
    page.getByText("Materials to delete: 2. Questions to delete: 1.", {
      exact: true,
    })
  ).toBeVisible()
  await page.getByRole("button", { name: "Cancel", exact: true }).click()
  await expect(
    page.getByRole("link", { name: "Empty child topic", exact: true })
  ).toBeVisible()
  await page
    .getByRole("combobox", { name: "Interface language" })
    .selectOption("pl")
  await page
    .getByRole("button", { name: "Usuń przedmiot", exact: true })
    .click()
  await expect(
    page.getByText("Tematy do usunięcia: 2.", { exact: true })
  ).toBeVisible()
  await page.screenshot({
    path: `/tmp/learning-subject-${testInfo.project.name}.png`,
    fullPage: true,
    animations: "disabled",
  })
  await page.getByRole("button", { name: "Usuń", exact: true }).click()
  await expect(page).toHaveURL(/#library$/)
  await expect(
    page.getByRole("link", { name: `History ${name}`, exact: true })
  ).toHaveCount(0)
  expect((await page.request.get(pdfDownload!)).status()).toBe(404)
  expect(
    (await page.request.get(`/api/documents/${captions.id}/download`)).status()
  ).toBe(404)
  await page
    .getByRole("combobox", { name: "Język interfejsu" })
    .selectOption("en")
  await page.goto(sessionURL)
  await expect(page.getByRole("heading", { name, exact: true })).toBeVisible()
  await expect(page.getByText(/Material deleted/)).toBeVisible()
  await expect(
    page.getByRole("link", { name: "Return to library", exact: true }).first()
  ).toHaveAttribute("href", "#library")
  await page
    .getByRole("button", { name: "Review difficult cards", exact: true })
    .click()
  await expect(page).toHaveURL(/#study\/\d+$/)
  await expect(page.getByRole("button", { name: /Nil/ })).toBeVisible()
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth + 1
    )
  ).toBe(true)
})

async function selectPractice(page: Page, label: string) {
  await page.getByRole("combobox", { name: "Practice method" }).click()
  await page.getByRole("option", { name: new RegExp(label) }).click()
}
