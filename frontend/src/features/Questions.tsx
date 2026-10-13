import { correctIndices } from "@/lib/answers"
import { t } from "@/i18n"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  CardFooter,
} from "@/components/ui/card"
import {
  Blank,
  Loading,
  ErrorNotice,
  EditCard,
  DeleteDialog,
  Sources,
} from "@/components/shared"
import { useQuery, navigate } from "@/api"
import type { Card as Question, Job, Topic } from "@/types"

export default function Questions({
  topic,
  cardId,
}: {
  topic: Topic
  cardId?: number
}) {
  const cards = useQuery<Question[]>(`/cards?topic_id=${topic.id}`)
  const jobs = useQuery<Job[]>("/jobs", 3000)
  const root = `#library/topic/${topic.id}`
  const current = cards.data?.find((card) => card.id === cardId)
  const pending =
    jobs.data?.filter(
      (job) =>
        ["generate", "prepare_quiz"].includes(job.kind) &&
        job.topic_ids?.includes(topic.id) &&
        !["succeeded", "cancelled"].includes(job.status)
    ) || []
  return (
    <div className="flex flex-col gap-4">
      <Button asChild variant="outline">
        <a href={cardId ? `${root}/questions` : `${root}/create`}>
          {cardId ? t("К вопросам") : t("Создать вопросы")}
        </a>
      </Button>
      <ErrorNotice message={cards.error} retry={cards.refetch} />
      {cards.loading ? (
        <Loading />
      ) : cardId ? (
        current ? (
          <Card>
            <CardHeader>
              <CardTitle>{current.question}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <p className="whitespace-pre-wrap">{current.answer}</p>
              {current.options.length > 0 && (
                <ol className="flex flex-col gap-2">
                  {current.options.map((option, index) => (
                    <li key={index}>
                      {correctIndices(current).includes(index) ? "✓ " : ""}
                      {option}
                    </li>
                  ))}
                </ol>
              )}
              <Sources sources={current.sources} />
            </CardContent>
            <CardFooter>
              <EditCard card={current} onSaved={cards.refetch} />
              <DeleteDialog
                path={`/cards/${current.id}`}
                name={current.question}
                label={t("Удалить вопрос")}
                onDeleted={() =>
                  navigate(`library/topic/${topic.id}/questions`)
                }
              />
            </CardFooter>
          </Card>
        ) : (
          <Blank
            title={t("Вопрос не найден")}
            description={t("Вернись к списку вопросов темы.")}
          />
        )
      ) : cards.data?.length ? (
        cards.data.map((card) => (
          <Card key={card.id}>
            <CardHeader>
              <CardTitle>
                <a href={`${root}/question/${card.id}`}>{card.question}</a>
              </CardTitle>
              <div className="flex flex-wrap gap-2">
                <Badge variant="outline">
                  {card.status === "saved"
                    ? t("Готов к занятиям")
                    : t("Черновик")}
                </Badge>
                {card.language && (
                  <Badge variant="secondary">{card.language}</Badge>
                )}
                {card.target_language && (
                  <Badge variant="outline">{t("Перевод")}</Badge>
                )}
                {card.status === "draft" && card.job_id && (
                  <a
                    className="text-sm underline"
                    href={`#generation/${card.job_id}`}
                  >
                    {t("Проверить и сохранить")}
                  </a>
                )}
              </div>
            </CardHeader>
            <CardFooter>
              <DeleteDialog
                path={`/cards/${card.id}`}
                name={card.question}
                label={t("Удалить вопрос")}
                onDeleted={cards.refetch}
              />
            </CardFooter>
          </Card>
        ))
      ) : (
        <Blank
          title={t("Пока нет вопросов")}
          description={t("Создай вопросы из материалов этой темы.")}
        />
      )}
      {pending.map((job) => (
        <Button key={job.id} variant="outline" asChild>
          <a
            href={`#${job.kind === "prepare_quiz" ? "prepare" : "generation"}/${job.id}`}
          >
            {job.kind === "prepare_quiz"
              ? t("Подготовка теста")
              : t("Создание вопросов")}{" "}
            · #{job.id}
          </a>
        </Button>
      ))}
    </div>
  )
}
