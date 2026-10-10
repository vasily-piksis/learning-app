import { useState } from "react"
import type { ReactNode } from "react"
import {
  AlertCircle,
  BookOpen,
  Loader2,
  Pencil,
  Check,
  RefreshCw,
} from "lucide-react"
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
import { Textarea } from "@/components/ui/textarea"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { api, errorText } from "@/api"
import type { Card, Job, Source } from "@/types"

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
      <AlertTitle>Не получилось</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        {message}
        {retry && (
          <Button variant="outline" onClick={retry}>
            Попробовать ещё раз
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
    <div className="flex flex-col gap-4" aria-label="Загрузка">
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
      <span>Из материалов:</span>
      {sources.map((s, i) => (
        <a
          key={i}
          href={`/api/documents/${s.document_id}/download`}
          target="_blank"
          rel="noreferrer"
        >
          {s.name || `Документ ${s.document_id}`} · стр. {s.page}
        </a>
      ))}
    </div>
  )
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
              Короткое название поможет легко найти материалы.
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
                <FieldLabel htmlFor="name">Название</FieldLabel>
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
                Отмена
              </Button>
              <Button disabled={busy || !name.trim()}>
                {busy && <PendingIcon />}Сохранить
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
export function EditCard({
  card,
  onSaved,
}: {
  card: Card
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false),
    [question, setQuestion] = useState(card.question),
    [answer, setAnswer] = useState(card.answer || ""),
    [options, setOptions] = useState(card.options),
    [correct, setCorrect] = useState(card.correct_index ?? 0),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  return (
    <>
      <Button
        variant="ghost"
        onClick={() => {
          setQuestion(card.question)
          setAnswer(card.answer || "")
          setOptions(card.options)
          setCorrect(card.correct_index ?? 0)
          setError(null)
          setOpen(true)
        }}
        aria-label="Изменить карточку"
      >
        <Pencil data-icon="inline-start" />
        Изменить
      </Button>
      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!busy) setOpen(v)
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Проверим карточку</DialogTitle>
            <DialogDescription>
              Можно уточнить вопрос, ответ и варианты перед занятием.
            </DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault()
              setBusy(true)
              try {
                await api(`/cards/${card.id}`, "PATCH", {
                  question,
                  answer,
                  options,
                  correct_index: card.mode === "quiz" ? correct : null,
                  version: card.version,
                })
                setOpen(false)
                onSaved()
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="question">Вопрос</FieldLabel>
                <Textarea
                  id="question"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  required
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="answer">Ответ</FieldLabel>
                <Textarea
                  id="answer"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  required
                />
              </Field>
              {card.mode === "quiz" &&
                options.map((option, i) => (
                  <Field key={i}>
                    <FieldLabel htmlFor={`option-${i}`}>
                      Вариант {i + 1}
                    </FieldLabel>
                    <div className="flex gap-2">
                      <Input
                        id={`option-${i}`}
                        value={option}
                        onChange={(e) =>
                          setOptions((o) =>
                            o.map((v, n) => (n === i ? e.target.value : v))
                          )
                        }
                        required
                      />
                      <Button
                        type="button"
                        variant={correct === i ? "default" : "outline"}
                        aria-pressed={correct === i}
                        aria-label={`Правильный вариант ${i + 1}`}
                        onClick={() => setCorrect(i)}
                      >
                        <Check />
                      </Button>
                    </div>
                  </Field>
                ))}
            </FieldGroup>
            <Sources sources={card.sources} />
            <ErrorNotice message={error} />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                Отмена
              </Button>
              <Button disabled={busy}>
                {busy && <PendingIcon />}Сохранить изменения
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
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
          ? "В очереди"
          : job.status === "running"
            ? "Готовим материалы"
            : job.status === "failed"
              ? "Задача не завершена"
              : "Готово"}
        <Badge variant="secondary">#{job.id}</Badge>
      </AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-3">
        {job.error || "Можно закрыть страницу. Результат будет сохранён."}
        {job.status === "failed" && retry && (
          <Button variant="outline" onClick={retry}>
            <RefreshCw data-icon="inline-start" />
            Повторить задачу
          </Button>
        )}
      </AlertDescription>
    </Alert>
  )
}
