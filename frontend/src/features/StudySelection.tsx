import { t } from "@/i18n"
import { useState } from "react"
import { Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { ErrorNotice, PendingIcon } from "@/components/shared"
import { api, errorText, navigate } from "@/api"
import type { Topic, Subject, StudySession, Job } from "@/types"
export default function StudySelection({
  topics,
  subjects,
}: {
  topics: Topic[]
  subjects: Subject[]
}) {
  const [selected, setSelected] = useState<number[]>([])
  const [mode, setMode] = useState<"flashcard" | "quiz">("flashcard")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const available = topics.filter((topic) => topic.card_count > 0)
  const chosen = selected.filter((id) =>
    available.some((topic) => topic.id === id)
  )
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" disabled={!available.length}>
          <Play data-icon="inline-start" />
          {t("Выбрать темы для повторения")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("Что повторим?")}</DialogTitle>
          <DialogDescription>
            {t(
              "Выбери одну или несколько тем. Флеш-карты используют все сохранённые вопросы. Тест использует те же вопросы."
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {available.map((topic) => (
            <label
              key={topic.id}
              className="flex cursor-pointer items-start gap-3 rounded-lg border p-3"
            >
              <Checkbox
                aria-label={topic.name}
                checked={selected.includes(topic.id)}
                disabled={busy}
                onCheckedChange={(checked) =>
                  setSelected((values) =>
                    checked
                      ? [...values, topic.id]
                      : values.filter((id) => id !== topic.id)
                  )
                }
              />
              <span className="min-w-0 break-words">
                {topic.name}
                <span className="block text-sm text-muted-foreground">
                  {
                    subjects.find((subject) => subject.id === topic.subject_id)
                      ?.name
                  }
                </span>
              </span>
            </label>
          ))}
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label={t("Формат занятия")}
          >
            {(["flashcard", "quiz"] as const).map((value) => (
              <Button
                key={value}
                variant={mode === value ? "secondary" : "outline"}
                aria-pressed={mode === value}
                disabled={busy}
                onClick={() => {
                  setMode(value)
                  setError(null)
                }}
              >
                {value === "quiz" ? t("Тест") : t("Флеш-карты")}
              </Button>
            ))}
          </div>
          <ErrorNotice message={error} />
        </div>
        <DialogFooter>
          <Button
            disabled={busy || !chosen.length}
            onClick={async () => {
              setBusy(true)
              setError(null)
              try {
                const session = await api<
                  StudySession | { preparation_job: Job }
                >("/study", "POST", {
                  topic_ids: chosen,
                  mode,
                })
                navigate(
                  "preparation_job" in session
                    ? `prepare/${session.preparation_job.id}`
                    : `study/${session.id}`
                )
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy && <PendingIcon />}
            {t("Начать занятие")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
