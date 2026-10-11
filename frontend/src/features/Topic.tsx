import { t } from "@/i18n"
import { ArrowLeft, FileText, ListChecks, Pencil, Plus } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card"
import {
  PageHeading,
  NameDialog,
  Loading,
  ErrorNotice,
  Blank,
} from "@/components/shared"
import { api, useQuery } from "@/api"
import type { Topic as TopicData } from "@/types"
import StartStudy from "./StartStudy"
import Materials from "./Materials"
import Questions from "./Questions"
import Generation from "./Generation"

export default function Topic({
  id,
  section,
  cardId,
}: {
  id: number
  section?: string
  cardId?: number
}) {
  const topics = useQuery<TopicData[]>("/topics")
  const topic = topics.data?.find((topic) => topic.id === id)
  if (topics.loading) return <Loading />
  if (topics.error)
    return <ErrorNotice message={topics.error} retry={topics.refetch} />
  if (!topic)
    return (
      <Blank
        title={t("Тема не найдена")}
        description={t("Выбери тему в библиотеке.")}
        action={
          <Button asChild>
            <a href="#library">{t("В библиотеку")}</a>
          </Button>
        }
      />
    )
  const root = `#library/topic/${id}`
  const labels: Record<string, string> = {
    materials: t("Материалы"),
    questions: t("Вопросы"),
    question: t("Вопрос"),
    create: t("Создать вопросы"),
  }
  return (
    <div className="flex flex-col gap-6">
      <div className="section-toolbar">
        <Button asChild variant="ghost">
          <a href={section ? root : `#library/subject/${topic.subject_id}`}>
            <ArrowLeft data-icon="inline-start" />
            {section ? t("К теме") : t("К темам")}
          </a>
        </Button>
        {!section && (
          <NameDialog
            title={t("Название темы")}
            initial={topic.name}
            trigger={
              <Button variant="ghost">
                <Pencil data-icon="inline-start" />
                {t("Переименовать")}
              </Button>
            }
            onSave={async (name) => {
              await api(`/topics/${id}`, "PATCH", { name })
              topics.refetch()
            }}
          />
        )}
      </div>
      <PageHeading
        eyebrow={section ? topic.name : t("Тема")}
        title={section ? labels[section] || topic.name : topic.name}
        description={
          section ? "" : t("Выбери, как проверить себя по этой теме.")
        }
      />
      {section === "materials" ? (
        <Materials topic={topic} refresh={topics.refetch} />
      ) : section === "questions" || section === "question" ? (
        <Questions topic={topic} cardId={cardId} />
      ) : section === "create" ? (
        <Generation initialTopics={[id]} />
      ) : (
        <>
          <p className="text-muted-foreground">
            {t("Готовых вопросов: {count}", { count: topic.card_count })}
          </p>
          <StartStudy topicIds={[id]} disabled={!topic.card_count} />
          {!topic.card_count && (
            <Blank
              title={t("Пока нет готовых вопросов")}
              description={t(
                "Добавь материалы и создай вопросы. После проверки они станут доступны для обоих способов повторения."
              )}
              action={
                <Button asChild>
                  <a
                    href={`${root}/${topic.document_count ? "create" : "materials"}`}
                  >
                    <Plus data-icon="inline-start" />
                    {topic.document_count
                      ? t("Создать вопросы")
                      : t("Добавить материалы")}
                  </a>
                </Button>
              }
            />
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>
                  <a
                    className="flex items-center gap-2"
                    href={`${root}/questions`}
                  >
                    <ListChecks className="size-5" />
                    {t("Вопросы")}
                  </a>
                </CardTitle>
                <CardDescription>
                  {t("Посмотреть и изменить вопросы темы.")}
                </CardDescription>
              </CardHeader>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>
                  <a
                    className="flex items-center gap-2"
                    href={`${root}/materials`}
                  >
                    <FileText className="size-5" />
                    {t("Материалы")}
                  </a>
                </CardTitle>
                <CardDescription>
                  {t("Учебники, фотографии и видео. Можно дополнить позже.")}
                </CardDescription>
              </CardHeader>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
