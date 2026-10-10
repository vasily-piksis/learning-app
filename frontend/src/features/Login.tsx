import { useState } from "react"
import { BookOpen, LockKeyhole, ArrowRight } from "lucide-react"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { ErrorNotice, PendingIcon } from "@/components/shared"
import { api, errorText } from "@/api"
import type { User } from "@/types"

export default function Login({ onLogin }: { onLogin: (user: User) => void }) {
  const [username, setUsername] = useState(""),
    [password, setPassword] = useState(""),
    [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false)
  return (
    <main className="login-page">
      <div className="login-intro">
        <a href="#" className="brand">
          <span className="brand-mark">
            <BookOpen />
          </span>
          учиться<span className="brand-dot">.</span>
        </a>
        <p className="eyebrow">Маленькие шаги. Большие открытия.</p>
        <h1>
          Знания остаются.
          <br />
          <span>Сложное становится понятным.</span>
        </h1>
        <p className="lead">
          Свои учебники, свои темы и карточки, к которым всегда можно вернуться.
        </p>
        <div className="login-caption">
          <LockKeyhole className="size-4" /> Семейная библиотека · личный
          прогресс
        </div>
      </div>
      <Card className="login-card">
        <CardHeader>
          <CardTitle className="text-2xl">Рады тебя видеть</CardTitle>
          <CardDescription>Войди, чтобы продолжить учиться.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-6"
            onSubmit={async (e) => {
              e.preventDefault()
              setBusy(true)
              setError(null)
              try {
                onLogin(
                  await api<User>("/auth/login", "POST", { username, password })
                )
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            <FieldGroup>
              <Field data-invalid={!!error}>
                <FieldLabel htmlFor="username">Логин</FieldLabel>
                <Input
                  id="username"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  aria-invalid={!!error}
                  placeholder="Твой логин"
                />
              </Field>
              <Field data-invalid={!!error}>
                <FieldLabel htmlFor="password">Пароль</FieldLabel>
                <Input
                  id="password"
                  type="password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  aria-invalid={!!error}
                  placeholder="Твой пароль"
                />
              </Field>
            </FieldGroup>
            <ErrorNotice message={error} />
            <Button disabled={busy} size="lg">
              {busy ? <PendingIcon /> : <ArrowRight data-icon="inline-end" />}
              Войти
            </Button>
            <p className="text-center text-xs text-muted-foreground">
              Аккаунты создаёт владелец семейной библиотеки.
            </p>
          </form>
        </CardContent>
      </Card>
    </main>
  )
}
