import { useState } from "react"
import { t } from "@/i18n"
import { api, APIError, errorText } from "@/api"
import type { User } from "@/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldDescription,
  FieldGroup,
  FieldLabel,
} from "@/components/ui/field"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { ErrorNotice, PendingIcon } from "@/components/shared"

export default function Profile({
  user,
  onChanged,
}: {
  user: User
  onChanged: (value: User) => void
}) {
  const [open, setOpen] = useState(false)
  const [current, setCurrent] = useState("")
  const [password, setPassword] = useState("")
  const [confirmation, setConfirmation] = useState("")
  const [busy, setBusy] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [invalid, setInvalid] = useState<
    "current" | "new" | "confirmation" | null
  >(null)
  function reset() {
    setCurrent("")
    setPassword("")
    setConfirmation("")
    setError(null)
    setInvalid(null)
    setSuccess(false)
  }
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (!busy) {
          reset()
          setOpen(value)
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="ghost" aria-label={t("Профиль")}>
          <span className="account-avatar" aria-hidden="true">
            {user.display_name[0]}
          </span>
          <span className="account-name">{user.display_name}</span>
        </Button>
      </DialogTrigger>
      <DialogContent showCloseButton={!busy}>
        <DialogHeader>
          <DialogTitle>{t("Профиль")}</DialogTitle>
          <DialogDescription>
            {t("Смена пароля для аккаунта «{name}».", { name: user.username })}
          </DialogDescription>
        </DialogHeader>
        {success ? (
          <>
            <p role="status">
              {t("Пароль изменён. Остальные устройства вышли из аккаунта.")}
            </p>
            <DialogFooter>
              <Button
                onClick={() => {
                  reset()
                  setOpen(false)
                }}
              >
                {t("Закрыть")}
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form
            className="flex flex-col gap-5"
            onSubmit={async (event) => {
              event.preventDefault()
              setError(null)
              setInvalid(null)
              if ([...password].length < 10) {
                setError("Новый пароль должен содержать минимум 10 символов")
                setInvalid("new")
                return
              }
              if (password !== confirmation) {
                setError("Пароли не совпадают")
                setInvalid("confirmation")
                return
              }
              setBusy(true)
              try {
                const value = await api<User>("/auth/password", "POST", {
                  current_password: current,
                  new_password: password,
                })
                onChanged(value)
                setCurrent("")
                setPassword("")
                setConfirmation("")
                setSuccess(true)
              } catch (failure) {
                setError(errorText(failure))
                if (failure instanceof APIError && failure.status === 401) {
                  if (failure.message === "Войдите в аккаунт")
                    window.dispatchEvent(new Event("auth-expired"))
                  else setInvalid("current")
                }
              } finally {
                setBusy(false)
              }
            }}
          >
            <FieldGroup>
              <Field data-invalid={invalid === "current"}>
                <FieldLabel htmlFor="profile-current-password">
                  {t("Текущий пароль")}
                </FieldLabel>
                <Input
                  id="profile-current-password"
                  autoFocus
                  type="password"
                  autoComplete="current-password"
                  required
                  maxLength={1024}
                  value={current}
                  onChange={(event) => setCurrent(event.target.value)}
                  disabled={busy}
                  aria-invalid={invalid === "current"}
                />
              </Field>
              <Field data-invalid={invalid === "new"}>
                <FieldLabel htmlFor="profile-new-password">
                  {t("Новый пароль")}
                </FieldLabel>
                <Input
                  id="profile-new-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  maxLength={1024}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled={busy}
                  aria-invalid={invalid === "new"}
                />
                <FieldDescription>{t("Минимум 10 символов.")}</FieldDescription>
              </Field>
              <Field data-invalid={invalid === "confirmation"}>
                <FieldLabel htmlFor="profile-confirm-password">
                  {t("Повторите новый пароль")}
                </FieldLabel>
                <Input
                  id="profile-confirm-password"
                  type="password"
                  autoComplete="new-password"
                  required
                  maxLength={1024}
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  disabled={busy}
                  aria-invalid={invalid === "confirmation"}
                />
              </Field>
            </FieldGroup>
            <ErrorNotice message={error} />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  reset()
                  setOpen(false)
                }}
              >
                {t("Отмена")}
              </Button>
              <Button disabled={busy}>
                {busy && <PendingIcon />}
                {t("Сменить пароль")}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  )
}
