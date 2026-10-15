import { expect, test } from "@playwright/test"
import { translations } from "../src/locales"

const text = {
  en: {
    input: "Your written response",
    grade: "Grade with AI (paid)",
    score: "Score: 75/100",
    result: "Session result",
    repeat: "Review difficult cards",
  },
  pl: {
    input: "Twoja swobodna odpowiedź",
    grade: "Oceń z AI (płatne)",
    score: "Wynik: 75/100",
    result: "Wynik sesji",
    repeat: "Powtórz trudne pytania",
  },
  ru: {
    input: "Твой развёрнутый ответ",
    grade: "Оценить с ИИ (платно)",
    score: "Оценка: 75/100",
    result: "Результат занятия",
    repeat: "Повторить сложные карточки",
  },
}
// A tiny real PNG enters the normal multipart decoder and private file lifecycle.
const png = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAUAAAAC0CAIAAABqhmJGAAAEcElEQVR4nO3dMZJUVRSA4R6LLZC6ADNSE3dhgitwBY/MbN4KWIEk7sLEEDMXYOomrHJKiyqEYaD73fvf930pA3Muxc95r7un++7+7V8XoOmr0QMAn0/AECZgCBMwhAkYwgQMYQKGMAFDmIAhTMAQJmAIEzCECRjCBAxhz0YPACNtL55/6Jf23wM/aStgzmj7cLfvf83MJQuYc9k+Id3//S1zZixgzmJ7errzZ+xBLE5h+7J6r/7nXMs6G/jV68f/Zu9/nOu/T46xXbW67cXzefbwXfpN7T4l2g8R80lst9mZkzScDPhLun2fkhe23fKKd4aGSwFft9v3KXkx2+3vV4c33Aj41um+S8Zr2I56tGlsw7M/iHVkuu9+RxmTMPXTSMfXO8O3pvVkzzb0iaV5Ax6e0PABIHkPPFs5LqdbthErcdSd8HQbeLZ65xwJZgx42lSmHYyTmyjgySOZfDzGPqQ06vvOEnAij8SQnMoUAYfCCI3KGYwPOJdEbmAWNj5goBpwdJtFx2Y9IwNOZ5AenmUMC3iBABY4AnXugSFsTMDL7K5lDrKMfdBrkr0WGihs4MW21mLHocU9MKvZD7+KHviuOgKGsKMDXvKCc8lDpe0HrsSxb2pnA0OYgFnTfshiHP6+0IcGvPCl5sJH69pvXNfwem1gFrffrLEZ6hUw69tvUNok9QqYU9iv2ts89R4a8PJ3icsfMG2/UnVT1Rv4bCS4lv2f9j777SNnS/eBgDmX/ekZz5nuAwFzRvu/TX6k5Jm7/Y+AObW9UOlHeCUWhAkYwgQMYQKGMAFDmIAhTMAQdlzA9z+2n3B71PIHZEI2MIQJGMIEDGGHBrzwXeLCR2NmNjCECRjCjg54yUvNJQ9Fgg0MYQKGsAEBL3bBudhxaLGBIWxMwMtsrWUOQpQNDGHDAl5gdy1wBOpGbuB0AOnhWcbgS+hoBtGxWY97YAgbH3Bum+UGZmHjA24lERqVM5gi4EoYiSE5lVkCnj+PycfjnCYKeOZIph2Mk5sr4DlTmXAkeHB3/3bSf52vXj/hM9RvRLpMbroNPE88wweAcMBjE1IvCfNeQo+6nJYuIY2Aj8lYuuSUAr5RybqlKxnwVUrWLQtoB/zg6x++u1wuL7/949GvfPPbN5fL5c+ffz1kLri5Z5dVPMQJpzL100jAxwkYwgQMYXeXny51b3552t3vy+8ff7gLEmxgCBMwhAkYwgQMYQKGMAFDmIAhTMAQJmAIEzCECRjCBAxhAoYwAUOYgCFMwBAmYAgTMIQJGMIEDGEChjABQ5iAIUzAECZgCBMwhAkYwgQMYQKGMAFD2AofLwqnZQNDmIAhTMAQJmAIEzCECRjCBAxhAoYwAUOYgCFMwBAmYAgTMIQJGMIEDGEChjABQ5iAIUzAECZgCBMwhAkYwgQMYQKGMAFDmIAhTMAQJmAIEzCECRjCBAxhAoYwAUOYgCFMwBAmYAgTMIQJGMIEDGEChjABQ5iAIUzAECZgCBMwhAkYwgQMYQKGS9ff7SkNUZaS1LYAAAAASUVORK5CYII=",
  "base64"
)
for (const locale of ["en", "pl", "ru"] as const)
  test(`${locale} image-only draft prepare save describe history repeat`, async ({
    page,
  }, info) => {
    const errors: string[] = []
    page.on("pageerror", (error) => errors.push(error.message))
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
    const subject = await (
      await page.request.post("/api/subjects", {
        headers,
        data: { name: `Picture ${locale} ${info.project.name}` },
      })
    ).json()
    const topic = await (
      await page.request.post("/api/topics", {
        headers,
        data: { name: "Obraz", subject_id: subject.id },
      })
    ).json()
    const label = (english: string) => {
      const entry = Object.entries(translations).find(([, value]) => value.en === english)
      if (!entry || locale === "en") return english
      return locale === "ru" ? entry[0] : entry[1].pl
    }
    await page.getByLabel("Interface language", { exact: true }).selectOption(locale)
    await page.goto(`/#library/topic/${topic.id}/create/picture_description`)
    await page
      .getByLabel(label("Source picture"), { exact: true })
      .setInputFiles({ name: label("field.png"), mimeType: "image/png", buffer: png })
    await page.getByLabel(label("Description language (pl, en, ru, lt)")).fill(locale)
    await page.getByRole("combobox", { name: label("CEFR level") }).click()
    await page.getByRole("option", { name: label("A1"), exact: true }).click()
    await page.getByLabel(label("Minimum words (optional)")).fill("100")
    await page
      .getByRole("button", { name: label("Create draft without AI"), exact: true })
      .click()
    await expect(
      page.getByText(label("First prepare and apply criteria based on the picture."))
    ).toBeVisible()
    await expect(
      page.getByRole("button", { name: label("Save"), exact: true })
    ).toBeDisabled()
    const drafts = await (
      await page.request.get(`/api/cards?topic_id=${topic.id}`)
    ).json()
    expect(drafts[0].sources).toEqual([])
    await page.evaluate(async () => {
      await document.fonts.ready
      window.scrollTo(0, 0)
      ;(document.activeElement as HTMLElement)?.blur()
      for (const animation of document.getAnimations()) animation.finish()
    })
    await page.screenshot({
      animations: "disabled",
      path: `/tmp/picture-${locale}-draft-${info.project.name}.png`,
      fullPage: true,
    })
    await page
      .getByRole("button", { name: label("Prepare criteria (paid)"), exact: true })
      .click()
    await expect(
      page.getByRole("button", { name: label("Apply variant"), exact: true })
    ).toBeVisible()
    if (locale === "en") {
      const jobs = (await (await page.request.get("/api/jobs")).json()) as {
        id: number
        kind: string
        result?: { card_id?: number; candidate?: unknown }
      }[]
      const preparation = jobs.find(
        (job) =>
          job.kind === "regenerate" && job.result?.card_id === drafts[0].id
      )!
      const replacement = await (
        await page.request.post(`/api/cards/${drafts[0].id}/image-candidates`, {
          headers,
          multipart: {
            slot: "question",
            version: "1",
            file: {
              name: label("replacement.png"),
              mimeType: "image/png",
              buffer: png,
            },
          },
        })
      ).json()
      const conflict = await page.request.post(
        `/api/jobs/${preparation.id}/apply-regeneration`,
        {
          headers,
          data: {
            candidate: preparation.result?.candidate,
            image_updates: { question: { asset_id: replacement.id } },
          },
        }
      )
      expect(conflict.status()).toBe(409)
      expect(
        (
          await page.request.delete(`/api/image-candidates/${replacement.id}`, {
            headers,
          })
        ).ok()
      ).toBeTruthy()
      expect(
        (
          await page.request.get(
            `/api/image-candidates/${replacement.id}/preview`
          )
        ).status()
      ).toBe(404)
    }
    await page.evaluate(async () => {
      await document.fonts.ready
      window.scrollTo(0, 0)
      ;(document.activeElement as HTMLElement)?.blur()
      for (const animation of document.getAnimations()) animation.finish()
    })
    await page.screenshot({
      animations: "disabled",
      path: `/tmp/picture-${locale}-criteria-${info.project.name}.png`,
      fullPage: false,
    })
    await page
      .getByRole("button", { name: label("Apply variant"), exact: true })
      .click()
    await expect(page.getByRole("dialog")).not.toBeVisible()
    await page.getByRole("button", { name: label("Save"), exact: true }).click()
    await page
      .getByRole("link", { name: label("Back to topic"), exact: true })
      .last()
      .click()
    await page.getByRole("combobox", { name: label("Practice method") }).click()
    await page.getByRole("option", { name: label("Picture description"), exact: false }).click()
    await page.getByRole("checkbox", { name: label("Enable paid AI grading") }).check()
    await page
      .getByRole("button", { name: label("Start studying"), exact: true })
      .click()
    await expect(page).toHaveURL(/#study\/\d+$/)
    const sessionId = page.url().split("/").pop()!
    const original = await (
      await page.request.get(`/api/study/${sessionId}`)
    ).json()
    expect(original.card.exercise).not.toHaveProperty("model_answer")
    await page.getByLabel(text[locale].input).fill("Na obrazku jest pole.")
    await expect(page.locator("main img").first()).toBeVisible()
    await page.evaluate(async () => {
      await document.fonts.ready
      window.scrollTo(0, 0)
      ;(document.activeElement as HTMLElement)?.blur()
      for (const animation of document.getAnimations()) animation.finish()
    })
    await page.screenshot({
      animations: "disabled",
      path: `/tmp/picture-${locale}-study-${info.project.name}.png`,
      fullPage: true,
    })
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth
      )
    ).toBe(true)
    await page
      .getByRole("button", { name: text[locale].grade, exact: true })
      .click()
    await expect(
      page.getByText(text[locale].score, { exact: true })
    ).toBeVisible()
    await page.evaluate(async () => {
      await document.fonts.ready
      window.scrollTo(0, 0)
      ;(document.activeElement as HTMLElement)?.blur()
      for (const animation of document.getAnimations()) animation.finish()
    })
    await page.screenshot({
      animations: "disabled",
      path: `/tmp/picture-${locale}-result-${info.project.name}.png`,
      fullPage: true,
    })
    await page.goto("/#history")
    await page.locator(`a[href="#study/${sessionId}"]`).click()
    await expect(
      page.getByText(text[locale].score, { exact: true })
    ).toBeVisible()
    await page
      .getByRole("button", { name: text[locale].repeat, exact: true })
      .click()
    await expect(page.getByLabel(text[locale].input)).toBeEnabled()
    const repeatId = page.url().split("/").pop()!
    const repeated = await (
      await page.request.get(`/api/study/${repeatId}`)
    ).json()
    expect(repeated.card.images.question.asset_id).toBe(
      original.card.images.question.asset_id
    )
    await page.request.delete(`/api/cards/${drafts[0].id}`, { headers })
    expect(
      (await page.request.get(repeated.card.images.question.url)).ok()
    ).toBeTruthy()
    expect(
      (
        await page.request.post("/api/study/delete", {
          headers,
          data: { session_ids: [Number(sessionId), Number(repeatId)] },
        })
      ).ok()
    ).toBeTruthy()
    expect(
      (await page.request.get(repeated.card.images.question.url)).status()
    ).toBe(404)
    expect(errors).toEqual([])
  })
