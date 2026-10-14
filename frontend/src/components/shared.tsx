import { t, systemMessage } from "@/i18n"
import { useState } from "react"
import type { ReactNode } from "react"
import { AlertCircle, BookOpen, Loader2, Trash2, RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  Empty,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  EmptyDescription,
  EmptyContent,
} from "@/components/ui/empty"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { api, errorText, APIError } from "@/api"
import type { Job, Source } from "@/types"

export function PageHeading({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <header className="page-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lead">{description}</p>
      </div>
      {action}
    </header>
  )
}
export function ErrorNotice({
  message,
  retry,
}: {
  message: string | null
  retry?: () => void
}) {
  if (!message) return null
  return (
    <Alert variant="destructive">
      <AlertCircle />
      <AlertTitle>{t("Не получилось")}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        {systemMessage(message)}
        {retry && (
          <Button variant="outline" onClick={retry}>
            {t("Попробовать ещё раз")}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  )
}
export function Blank({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <Empty className="min-h-56">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <BookOpen />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{description}</EmptyDescription>
      </EmptyHeader>
      {action && <EmptyContent>{action}</EmptyContent>}
    </Empty>
  )
}
export function Loading() {
  return (
    <div className="flex flex-col gap-4" aria-label={t("Загрузка")}>
      <Skeleton className="h-8 w-2/3" />
      <Skeleton className="h-32 w-full" />
    </div>
  )
}
export function PendingIcon() {
  return <Loader2 data-icon="inline-start" className="animate-spin" />
}
export function Sources({ sources }: { sources: Source[] }) {
  if (!sources.length) return null
  return (
    <div className="sources">
      <span>{t("Из материалов:")}</span>
      {sources.map((s, i) =>
        s.available === false ? (
          <span key={i}>
            {s.name || t("Документ {id}", { id: s.document_id })} ·{" "}
            {t("Материал удалён")}
          </span>
        ) : (
          <a
            key={i}
            href={s.url || `/api/documents/${s.document_id}/download`}
            target="_blank"
            rel="noreferrer"
          >
            {s.name || t("Документ {id}", { id: s.document_id })} ·{" "}
            {s.start_seconds !== undefined
              ? timeLabel(s.start_seconds)
              : t("стр. {page}", { page: s.page })}
          </a>
        )
      )}
    </div>
  )
}
function timeLabel(seconds: number) {
  const value = Math.floor(seconds),
    hours = Math.floor(value / 3600)
  return `${hours ? `${String(hours).padStart(2, "0")}:` : ""}${String(Math.floor(value / 60) % 60).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`
}
export function NameDialog({
  title,
  initial = "",
  trigger,
  onSave,
}: {
  title: string
  initial?: string
  trigger: ReactNode
  onSave: (name: string) => Promise<unknown>
}) {
  const [open, setOpen] = useState(false),
    [name, setName] = useState(initial),
    [error, setError] = useState<string | null>(null),
    [busy, setBusy] = useState(false)
  return (
    <>
      <span
        onClick={() => {
          setName(initial)
          setError(null)
          setOpen(true)
        }}
      >
        {trigger}
      </span>
      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!busy) setOpen(v)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>
              {t("Короткое название поможет легко найти материалы.")}
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={async (e) => {
              e.preventDefault()
              setBusy(true)
              setError(null)
              try {
                await onSave(name.trim())
                setOpen(false)
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
            className="flex flex-col gap-4"
          >
            <FieldGroup>
              <Field data-invalid={!!error}>
                <FieldLabel htmlFor="name">{t("Название")}</FieldLabel>
                <Input
                  id="name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={200}
                  required
                  autoFocus
                  aria-invalid={!!error}
                />
              </Field>
            </FieldGroup>
            <ErrorNotice message={error} />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                {t("Отмена")}
              </Button>
              <Button disabled={busy || !name.trim()}>
                {busy && <PendingIcon />}
                {t("Сохранить")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
export { default as EditCard } from "@/features/exercises/EditQuestion"

export function JobNotice({ job, retry }: { job: Job; retry?: () => void }) {
  return (
    <Alert>
      <AlertTitle className="flex items-center gap-2">
        {job.status === "queued" || job.status === "running" ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <BookOpen />
        )}
        {job.status === "queued"
          ? t("В очереди")
          : job.status === "running"
            ? t("Готовим материалы")
            : job.status === "failed"
              ? t("Задача не завершена")
              : job.status === "cancelled"
                ? t("Отменено")
                : t("Готово")}
        <Badge variant="secondary">#{job.id}</Badge>
      </AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        {job.error
          ? systemMessage(job.error)
          : t("Можно закрыть страницу. Результат будет сохранён.")}
        {job.status === "failed" && retry && (
          <Button variant="outline" onClick={retry}>
            <RefreshCw data-icon="inline-start" />
            {t("Повторить задачу")}
          </Button>
        )}
      </AlertDescription>
    </Alert>
  )
}

export function DeleteDialog({
  path,
  name,
  label,
  onDeleted,
}: {
  path: string
  name: string
  label: string
  onDeleted: () => void
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [counts, setCounts] = useState<{
    card_count: number
    document_count: number
    topic_count?: number
    revision?: string
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function show() {
    setOpen(true)
    setBusy(true)
    setError(null)
    setCounts(null)
    try {
      setCounts(
        path.startsWith("/cards/")
          ? { card_count: 1, document_count: 0 }
          : await api(`${path}/deletion`)
      )
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <Button variant="outline" onClick={() => void show()}>
        <Trash2 data-icon="inline-start" />
        {label}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value)
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{label}</DialogTitle>
            <DialogDescription>
              {t("Удалить «{name}»?", { name })}{" "}
              {t("Это действие нельзя отменить. История занятий сохранится.")}
            </DialogDescription>
          </DialogHeader>
          {counts?.topic_count !== undefined && (
            <p>
              {t("Тем будет удалено: {topics}.", {
                topics: counts.topic_count,
              })}
            </p>
          )}
          {counts && (
            <p>
              {t(
                "Материалов будет удалено: {documents}. Вопросов будет удалено: {cards}.",
                { documents: counts.document_count, cards: counts.card_count }
              )}
            </p>
          )}
          {busy && <Loading />}
          <ErrorNotice message={error} />
          <DialogFooter>
            <Button
              variant="outline"
              disabled={busy}
              autoFocus
              onClick={() => setOpen(false)}
            >
              {t("Отмена")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy || !counts}
              onClick={async () => {
                setBusy(true)
                setError(null)
                try {
                  await api(path, "DELETE", { revision: counts?.revision })
                  setOpen(false)
                  onDeleted()
                } catch (e) {
                  setError(errorText(e))
                  if (e instanceof APIError && e.status === 409) {
                    setCounts(null)
                    try {
                      setCounts(await api(`${path}/deletion`))
                    } catch (refreshError) {
                      setError(errorText(refreshError))
                    }
                  }
                } finally {
                  setBusy(false)
                }
              }}
            >
              {t("Удалить")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
