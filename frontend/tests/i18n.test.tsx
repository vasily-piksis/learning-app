import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { expect, test, vi } from "vitest"
import App from "../src/App"
import { translations } from "../src/locales"
import { t } from "../src/i18n"
import { readFileSync, readdirSync } from "node:fs"
import ts from "typescript"
import { resolve } from "node:path"

test("Polish is default and interface language changes persist without changing content", async () => {
  localStorage.removeItem("learning-ui-language")
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify(
            url.endsWith("/auth/me")
              ? { id: 1, display_name: "Anna", csrf_token: "token" }
              : url.endsWith("/subjects")
                ? [{ id: 1, name: "English literature", topic_count: 1 }]
                : []
          )
        )
    )
  )
  const view = render(<App />)
  expect(await screen.findByRole("link", { name: "Biblioteka" })).toBeVisible()
  expect(
    await screen.findByRole("link", { name: "English literature" })
  ).toBeVisible()
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "Język interfejsu" }),
    "en"
  )
  expect(await screen.findByRole("link", { name: "Library" })).toBeVisible()
  expect(localStorage.getItem("learning-ui-language")).toBe("en")
  expect(document.documentElement.lang).toBe("en")
  view.unmount()
  render(<App />)
  expect(await screen.findByRole("link", { name: "Library" })).toBeVisible()
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "Interface language" }),
    "ru"
  )
  expect(await screen.findByRole("link", { name: "Библиотека" })).toBeVisible()
  expect(
    await screen.findByRole("link", { name: "English literature" })
  ).toBeVisible()
})

test("language switcher is available before login", async () => {
  localStorage.removeItem("learning-ui-language")
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(JSON.stringify({ detail: "Войдите в аккаунт" }), {
          status: 401,
        })
    )
  )
  render(<App />)
  expect(await screen.findByLabelText("Hasło")).toBeVisible()
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "Język interfejsu" }),
    "en"
  )
  expect(await screen.findByLabelText("Password")).toBeVisible()
})

test("a visible server error follows the interface language switch", async () => {
  localStorage.setItem("learning-ui-language", "pl")
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async (url: string) =>
        new Response(
          JSON.stringify({
            detail: url.endsWith("/login")
              ? "Неверный логин или пароль"
              : "Войдите в аккаунт",
          }),
          { status: 401 }
        )
    )
  )
  render(<App />)
  await userEvent.type(await screen.findByLabelText("Login"), "child")
  await userEvent.type(screen.getByLabelText("Hasło"), "wrong")
  await userEvent.click(screen.getByRole("button", { name: "Zaloguj się" }))
  expect(await screen.findByText("Nieprawidłowy login lub hasło")).toBeVisible()
  await userEvent.selectOptions(
    screen.getByRole("combobox", { name: "Język interfejsu" }),
    "en"
  )
  expect(
    await screen.findByText("Incorrect username or password")
  ).toBeVisible()
})

test("every interface translation key has Polish and English text", () => {
  const root = resolve(process.cwd(), "src")
  const files = [
    "App.tsx",
    "components/shared.tsx",
    "components/LanguageSwitcher.tsx",
    ...readdirSync(resolve(root, "features"))
      .filter((file) => file.endsWith(".tsx"))
      .map((file) => `features/${file}`),
  ]
  for (const file of files) {
    const parsed = ts.createSourceFile(
      file,
      readFileSync(resolve(root, file), "utf8"),
      ts.ScriptTarget.Latest,
      true,
      ts.ScriptKind.TSX
    )
    function visit(node: ts.Node) {
      if (
        ts.isCallExpression(node) &&
        node.expression.getText(parsed) === "t" &&
        node.arguments[0] &&
        ts.isStringLiteral(node.arguments[0])
      ) {
        const source = node.arguments[0].text
        expect(translations[source], `${file}: ${source}`).toBeDefined()
        expect(translations[source].pl).toBeTruthy()
        expect(translations[source].en).toBeTruthy()
      }
      ts.forEachChild(node, visit)
    }
    visit(parsed)
  }
  localStorage.setItem("learning-ui-language", "pl")
  expect(t("Загрузить {count} файлов", { count: 2 })).toBe("Prześlij pliki (2)")
})
