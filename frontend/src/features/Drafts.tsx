import { correctIndices } from "@/lib/answers"
import { questionLabel } from "@/lib/exercises"
import ExerciseSolution from "./exercises/ExerciseSolution"
import { t, systemMessage } from "@/i18n"
import { useState } from "react"
import { Check } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  ErrorNotice,
  Loading,
  Blank,
  PendingIcon,
  EditCard,
  DeleteDialog,
  Sources,
} from "@/components/shared"
import { api, useQuery, errorText, navigate } from "@/api"
import type { Job, Card as StudyCard } from "@/types"
export default function Drafts({ job }: { job: Job }) {
  const cards = useQuery<StudyCard[]>(`/cards?job_id=${job.id}`),
    [selected, setSelected] = useState<number[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const drafts = cards.data?.filter((c) => c.status === "draft") || []
  return (
    <div className="flex flex-col gap-4">
      <div className="section-toolbar">
        <h2>{t("Проверим карточки")}</h2>
        <Button
          variant="ghost"
          disabled={!drafts.length}
          onClick={() => setSelected(drafts.map((c) => c.id))}
        >
          {t("Выбрать все")}
        </Button>
      </div>
      {job.result?.warnings?.map((warning, i) => (
        <Alert key={i}>
          <AlertTitle>{t("Материалов оказалось меньше")}</AlertTitle>
          <AlertDescription>{systemMessage(warning)}</AlertDescription>
        </Alert>
      ))}
      <ErrorNotice message={cards.error || error} retry={cards.refetch} />
      {cards.loading ? (
        <Loading />
      ) : cards.data?.length ? (
        cards.data.map((card) => (
          <Card key={card.id}>
            <CardHeader>
              <div className="flex items-start gap-3">
                {card.status === "draft" ? (
                  <Checkbox
                    aria-label={t("Выбрать: {question}", {
                      question: card.question,
                    })}
                    checked={selected.includes(card.id)}
                    onCheckedChange={(v) =>
                      setSelected((ids) =>
                        v
                          ? [...ids, card.id]
                          : ids.filter((id) => id !== card.id)
                      )
                    }
                  />
                ) : (
                  <Badge variant="secondary">{t("Сохранена")}</Badge>
                )}
                <div className="flex flex-col gap-2">
                  <CardTitle>{card.question}</CardTitle>
                  <Badge variant="outline">
                    {questionLabel(card.question_type)}
                  </Badge>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <ExerciseSolution card={card} />
              {card.mode === "quiz" && (
                <ol className="flex flex-col gap-2">
                  {card.options.map((v, i) => (
                    <li key={i} className="flex items-center gap-2">
                      {correctIndices(card).includes(i) && (
                        <Check className="size-4 text-primary" />
                      )}
                      {v}
                    </li>
                  ))}
                </ol>
              )}
              <Sources sources={card.sources} />
            </CardContent>
            <CardFooter>
              <EditCard card={card} onSaved={cards.refetch} />
              <DeleteDialog
                path={`/cards/${card.id}`}
                name={card.question}
                label={t("Удалить вопрос")}
                onDeleted={() => {
                  setSelected((ids) => ids.filter((id) => id !== card.id))
                  cards.refetch()
                }}
              />
            </CardFooter>
          </Card>
        ))
      ) : (
        <Blank
          title={t("Карточки не созданы")}
          description={t(
            "Попробуй добавить материалы или запросить меньше вопросов."
          )}
        />
      )}
      {drafts.length > 0 && (
        <Button
          disabled={busy || !selected.length}
          onClick={async () => {
            setBusy(true)
            try {
              await api("/cards/save", "POST", { card_ids: selected })
              toast.success(t("Карточки сохранены в темах"))
              setSelected([])
              cards.refetch()
            } catch (e) {
              setError(errorText(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy && <PendingIcon />}
          {t("Сохранить выбранные ({count})", { count: selected.length })}
        </Button>
      )}
      {cards.data?.some((c) => c.status === "saved") && (
        <Button
          variant="outline"
          onClick={() =>
            navigate(
              job.topic_ids?.length === 1
                ? `library/topic/${job.topic_ids[0]}`
                : "library"
            )
          }
        >
          {t("Перейти к занятиям")}
        </Button>
      )}
    </div>
  )
}
