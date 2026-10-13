import { expect, test } from "@playwright/test"

test("profile changes password, keeps this device and signs out another device", async ({
  page,
  browser,
}, testInfo) => {
  const username = `profile_${testInfo.project.name}`
  const oldPassword = "browser-profile-password"
  const newPassword = "updated-browser-profile-password"
  async function login(password: string) {
    await page.goto("/")
    await page.getByLabel("Login", { exact: true }).fill(username)
    await page.getByLabel("Hasło", { exact: true }).fill(password)
    await page.getByRole("button", { name: "Zaloguj się", exact: true }).click()
  }
  await login(oldPassword)
  await expect(
    page.getByRole("button", { name: "Profil", exact: true })
  ).toBeVisible()
  const origin = new URL(page.url()).origin
  const other = await browser.newContext()
  try {
    const secondLogin = await other.request.post(`${origin}/api/auth/login`, {
      headers: { Origin: origin },
      data: { username, password: oldPassword },
    })
    expect(secondLogin.status()).toBe(200)
    const errors: string[] = []
    page.on("pageerror", (error) => errors.push(error.message))
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning")
        errors.push(message.text())
    })
    await page.getByRole("button", { name: "Profil", exact: true }).click()
    const dialog = page.getByRole("dialog")
    await expect(
      dialog.getByLabel("Obecne hasło", { exact: true })
    ).toBeFocused()
    await dialog.getByLabel("Obecne hasło", { exact: true }).fill(oldPassword)
    await dialog.getByLabel("Nowe hasło", { exact: true }).fill(newPassword)
    await dialog
      .getByLabel("Powtórz nowe hasło", { exact: true })
      .fill("different-password")
    await dialog
      .getByRole("button", { name: "Zmień hasło", exact: true })
      .click()
    await expect(dialog.getByRole("alert")).toContainText(
      "Hasła nie są identyczne"
    )
    await expect(
      dialog.getByLabel("Powtórz nowe hasło", { exact: true })
    ).toHaveAttribute("aria-invalid", "true")
    await dialog
      .getByLabel("Powtórz nowe hasło", { exact: true })
      .fill(newPassword)
    await page.screenshot({
      path: `/tmp/learning-profile-${testInfo.project.name}.png`,
      fullPage: false,
      animations: "disabled",
    })
    await dialog
      .getByRole("button", { name: "Zmień hasło", exact: true })
      .click()
    await expect(dialog.getByRole("status")).toContainText(
      "Hasło zostało zmienione."
    )
    expect((await page.request.get("/api/auth/me")).status()).toBe(200)
    expect((await other.request.get(`${origin}/api/auth/me`)).status()).toBe(
      401
    )
    await dialog
      .getByRole("button", { name: "Zamknij", exact: true })
      .last()
      .click()
    await page.reload()
    await expect(
      page.getByRole("button", { name: "Profil", exact: true })
    ).toBeVisible()
    await expect(
      page
        .getByRole("button", { name: "Profil", exact: true })
        .locator(".account-avatar")
    ).toBeVisible()
    expect(errors).toEqual([])
    await page.getByRole("button", { name: "Wyloguj się", exact: true }).click()
    await expect(page.getByLabel("Login", { exact: true })).toBeVisible()
    // The rejected old-password login intentionally produces a 401 resource error.
    page.removeAllListeners("console")
    await login(oldPassword)
    await expect(page.getByRole("alert")).toBeVisible()
    await page.getByLabel("Hasło", { exact: true }).fill(newPassword)
    await page.getByRole("button", { name: "Zaloguj się", exact: true }).click()
    await expect(
      page.getByRole("button", { name: "Profil", exact: true })
    ).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1
      )
    ).toBe(true)
  } finally {
    await other.close()
  }
})
