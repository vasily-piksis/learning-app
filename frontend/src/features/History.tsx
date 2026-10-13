import { useState } from "react"
import { t, getLocale } from "@/i18n"
import { ArrowRight, Clock, Check, RotateCcw, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Progress } from "@/components/ui/progress"
import { PageHeading, ErrorNotice, Loading, Blank } from "@/components/shared"
import { api, APIError, errorText, useQuery } from "@/api"
import type { StudySession } from "@/types"

export default function History() {
  const sessions = useQuery<StudySession[]>("/study")
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<number[]>([])
  const [removed, setRemoved] = useState<number[]>([])
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletedCount, setDeletedCount] = useState<number | null>(null)
  const shown = (sessions.data || []).filter((s) => !removed.includes(s.id))
  const active = shown.filter((s) => s.status === "active"),
    completed = shown.filter((s) => s.status === "completed")
  const selectedIds = shown
    .filter((s) => selected.includes(s.id))
    .map((s) => s.id)
  const allSelected = shown.length > 0 && selectedIds.length === shown.length
  function toggle(identifier: number, checked: boolean) {
    setSelected((previous) =>
      checked
        ? [...previous, identifier]
        : previous.filter((id) => id !== identifier)
    )
  }
  async function removeSelected() {
    setBusy(true)
    setError(null)
    try {
      const result = await api<{ deleted_count: number }>(
        "/study/delete",
        "POST",
        { session_ids: selectedIds }
      )
      setRemoved((previous) => [...previous, ...selectedIds])
      setDeletedCount(result.deleted_count)
      setSelected([])
      setSelecting(false)
      setOpen(false)
      sessions.refetch()
    } catch (e) {
      setError(errorText(e))
      if (e instanceof APIError && e.status === 404) {
        setOpen(false)
        setSelected([])
        sessions.refetch()
      }
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        eyebrow={t("Твой собственный темп")}
        title={t("Каждый шаг считается")}
        description={t(
          "Продолжи с того места, где остановилась, или вернись к сложным карточкам."
        )}
        action={
          shown.length > 0 && (
            <Button
              variant="outline"
              disabled={busy}
              onClick={() => {
                setSelecting((value) => !value)
                setSelected([])
                setDeletedCount(null)
                setError(null)
              }}
            >
              {selecting ? t("Завершить выбор") : t("Выбрать занятия")}
            </Button>
          )
        }
      />
      <ErrorNotice message={sessions.error} retry={sessions.refetch} />
      {!open && <ErrorNotice message={error} />}
      {deletedCount !== null && (
        <p role="status">
          {t("Удалено занятий: {count}.", { count: deletedCount })}
        </p>
      )}
      {selecting && shown.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <Button
            variant="outline"
            disabled={busy}
            onClick={() =>
              setSelected(allSelected ? [] : shown.map((s) => s.id))
            }
          >
            {allSelected ? t("Снять выделение") : t("Выбрать все показанные")}
          </Button>
          <Button
            variant="destructive"
            disabled={busy || selectedIds.length === 0}
            onClick={() => {
              setError(null)
              setOpen(true)
            }}
          >
            <Trash2 data-icon="inline-start" />
            {t("Удалить выбранные ({count})", { count: selectedIds.length })}
          </Button>
        </div>
      )}
      {sessions.loading ? (
        <Loading />
      ) : !shown.length ? (
        <Blank
          title={t("Первое занятие ещё впереди")}
          description={t(
            "Сохрани карточки в библиотеке и начни повторение. Здесь появится твоя личная история."
          )}
          action={
            <Button asChild>
              <a href="#library">
                {t("Выбрать тему")}
                <ArrowRight data-icon="inline-end" />
              </a>
            </Button>
          }
        />
      ) : (
        <>
          {active.length > 0 && (
            <section className="flex flex-col gap-4">
              <h2>{t("Продолжить учиться")}</h2>
              <div className="history-grid">
                {active.map((value) => (
                  <SessionCard
                    key={value.id}
                    session={value}
                    selecting={selecting}
                    checked={selected.includes(value.id)}
                    disabled={busy}
                    onCheckedChange={(checked) => toggle(value.id, checked)}
                  />
                ))}
              </div>
            </section>
          )}
          {completed.length > 0 && (
            <section className="flex flex-col gap-4">
              <h2>{t("Завершённые занятия")}</h2>
              <div className="history-grid">
                {completed.map((value) => (
                  <SessionCard
                    key={value.id}
                    session={value}
                    selecting={selecting}
                    checked={selected.includes(value.id)}
                    disabled={busy}
                    onCheckedChange={(checked) => toggle(value.id, checked)}
                  />
                ))}
              </div>
            </section>
          )}
        </>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!busy) setOpen(value)
        }}
      >
        <DialogContent showCloseButton={!busy}>
          <DialogHeader>
            <DialogTitle>{t("Удалить выбранные занятия?")}</DialogTitle>
            <DialogDescription>
              {t(
                "Ответы и объяснения этих занятий будут удалены без возможности восстановления. Библиотека и материалы сохранятся."
              )}
            </DialogDescription>
          </DialogHeader>
          <p>
            {t("Будет удалено занятий: {count}.", {
              count: selectedIds.length,
            })}
          </p>
          <ErrorNotice message={error} />
          <DialogFooter>
            <Button
              variant="outline"
              autoFocus
              disabled={busy}
              onClick={() => setOpen(false)}
            >
              {t("Отмена")}
            </Button>
            <Button
              variant="destructive"
              disabled={busy || !selectedIds.length}
              onClick={() => void removeSelected()}
            >
              {busy ? t("Удаляем…") : t("Удалить")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
function SessionCard({
  session,
  selecting,
  checked,
  disabled,
  onCheckedChange,
}: {
  session: StudySession
  selecting: boolean
  checked: boolean
  disabled: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  const done = session.status === "completed"
  return (
    <Card className={selecting && checked ? "ring-2 ring-primary" : undefined}>
      <CardHeader>
        {selecting && (
          <Field orientation="horizontal">
            <Checkbox
              id={`select-session-${session.id}`}
              checked={checked}
              disabled={disabled}
              onCheckedChange={(value) => onCheckedChange(value === true)}
            />
            <FieldLabel htmlFor={`select-session-${session.id}`}>
              {t("Выбрать занятие #{id}", { id: session.id })}
            </FieldLabel>
          </Field>
        )}
        <div className="flex items-center gap-2">
          <Badge variant={done ? "secondary" : "outline"}>
            {done ? <Check /> : <Clock />}
            {done ? t("Завершено") : t("В процессе")}
          </Badge>
          <Badge variant="outline">
            {session.mode === "quiz" ? t("Тест") : t("Флеш-карты")}
          </Badge>
        </div>
        <CardTitle className="text-xl">
          {session.topic_names.join(" · ")}
        </CardTitle>
        <CardDescription>
          {new Date(session.created + "Z").toLocaleDateString(getLocale(), {
            day: "numeric",
            month: "long",
            year: "numeric",
          })}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <p className="text-sm">
          {done
            ? t("{correct} из {count} {result}", {
                correct: session.correct,
                count: session.count,
                result: session.mode === "quiz" ? t("верно") : t("помнишь"),
              })
            : t("Пройдено {answered} из {count}", {
                answered: session.answered,
                count: session.count,
              })}
        </p>
        <Progress value={(session.answered / session.count) * 100} />
      </CardContent>
      <CardFooter>
        <Button asChild variant={done ? "outline" : "default"}>
          <a href={`#study/${session.id}`}>
            {done ? (
              <RotateCcw data-icon="inline-start" />
            ) : (
              <ArrowRight data-icon="inline-start" />
            )}
            {done ? t("Посмотреть результат") : t("Продолжить")}
          </a>
        </Button>
      </CardFooter>
    </Card>
  )
}
