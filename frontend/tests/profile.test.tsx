import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, expect, test, vi } from "vitest"
import App from "../src/App"

const user = {
  id: 1,
  username: "child",
  display_name: "Дочка",
  csrf_token: "old-token",
}
beforeEach(() => localStorage.setItem("learning-ui-language", "ru"))

function server(fail = false) {
  const changes: unknown[] = []
  let logoutCsrf = ""
  vi.stubGlobal("fetch", async (path: string, init: RequestInit) => {
    if (path === "/api/auth/me") return Response.json(user)
    if (path === "/api/subjects") return Response.json([])
    if (path === "/api/auth/password") {
      changes.push(JSON.parse(String(init.body)))
      return fail
        ? Response.json({ detail: "Неверный текущий пароль" }, { status: 401 })
        : Response.json({ ...user, csrf_token: "new-token" })
    }
    if (path === "/api/auth/logout") {
      logoutCsrf = (init.headers as Record<string, string>)["X-CSRF-Token"]
      return Response.json({ ok: true })
    }
    throw new Error(`Unexpected request: ${path}`)
  })
  return { changes, logoutCsrf: () => logoutCsrf }
}

async function open() {
  await userEvent.click(
    await screen.findByRole("button", { name: "Профиль", exact: true })
  )
  return screen.getByRole("dialog")
}

test("profile validates confirmation, changes password and uses the rotated CSRF token", async () => {
  const boundary = server()
  render(<App />)
  const dialog = await open()
  expect(within(dialog).getByLabelText("Текущий пароль")).toHaveFocus()
  await userEvent.type(
    within(dialog).getByLabelText("Текущий пароль"),
    "old-family-password"
  )
  await userEvent.type(
    within(dialog).getByLabelText("Новый пароль"),
    "new-family-password"
  )
  await userEvent.type(
    within(dialog).getByLabelText("Повторите новый пароль"),
    "different-password"
  )
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Сменить пароль" })
  )
  expect(within(dialog).getByText("Пароли не совпадают")).toBeVisible()
  expect(
    within(dialog).getByLabelText("Повторите новый пароль")
  ).toHaveAttribute("aria-invalid", "true")
  expect(boundary.changes).toEqual([])
  await userEvent.clear(within(dialog).getByLabelText("Повторите новый пароль"))
  await userEvent.type(
    within(dialog).getByLabelText("Повторите новый пароль"),
    "new-family-password"
  )
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Сменить пароль" })
  )
  expect(await within(dialog).findByRole("status")).toHaveTextContent(
    "Пароль изменён. Остальные устройства вышли из аккаунта."
  )
  expect(
    within(dialog).queryByLabelText("Текущий пароль")
  ).not.toBeInTheDocument()
  expect(boundary.changes).toEqual([
    {
      current_password: "old-family-password",
      new_password: "new-family-password",
    },
  ])
  await userEvent.click(
    within(dialog).getAllByRole("button", { name: "Закрыть", exact: true })[0]
  )
  await userEvent.click(
    screen.getByRole("button", { name: "Выйти", exact: true })
  )
  expect(boundary.logoutCsrf()).toBe("new-token")
  expect(await screen.findByLabelText("Логин")).toBeVisible()
})

test("wrong current password shows an error without signing out", async () => {
  server(true)
  render(<App />)
  const dialog = await open()
  await userEvent.type(
    within(dialog).getByLabelText("Текущий пароль"),
    "wrong-password"
  )
  await userEvent.type(
    within(dialog).getByLabelText("Новый пароль"),
    "new-family-password"
  )
  await userEvent.type(
    within(dialog).getByLabelText("Повторите новый пароль"),
    "new-family-password"
  )
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Сменить пароль" })
  )
  expect(
    await within(dialog).findByText("Неверный текущий пароль")
  ).toBeVisible()
  expect(within(dialog).getByLabelText("Текущий пароль")).toHaveAttribute(
    "aria-invalid",
    "true"
  )
  expect(screen.queryByLabelText("Логин")).not.toBeInTheDocument()
})

test("short new password never reaches the server", async () => {
  const boundary = server()
  render(<App />)
  const dialog = await open()
  await userEvent.type(
    within(dialog).getByLabelText("Текущий пароль"),
    "old-family-password"
  )
  await userEvent.type(within(dialog).getByLabelText("Новый пароль"), "tiny")
  await userEvent.type(
    within(dialog).getByLabelText("Повторите новый пароль"),
    "tiny"
  )
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Сменить пароль" })
  )
  expect(within(dialog).getByRole("alert")).toHaveTextContent(
    "Новый пароль должен содержать минимум 10 символов"
  )
  expect(boundary.changes).toEqual([])
})

test("closing profile clears entered passwords", async () => {
  server()
  render(<App />)
  const dialog = await open()
  await userEvent.type(
    within(dialog).getByLabelText("Текущий пароль"),
    "never-store-this"
  )
  await userEvent.click(
    within(dialog).getByRole("button", { name: "Отмена", exact: true })
  )
  const reopened = await open()
  expect(within(reopened).getByLabelText("Текущий пароль")).toHaveValue("")
})
