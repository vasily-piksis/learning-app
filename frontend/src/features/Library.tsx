import { t } from "@/i18n"
import { BookOpen, Plus, ArrowLeft, Pencil, FolderOpen } from "lucide-react"
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
import { api, useQuery, navigate } from "@/api"
import type { Subject, Topic } from "@/types"
import StudySelection from "./StudySelection"

export default function Library({
  subjectId,
  displayName,
}: {
  subjectId?: number
  displayName: string
}) {
  const subjects = useQuery<Subject[]>("/subjects"),
    topics = useQuery<Topic[]>("/topics")
  const selected = subjects.data?.find((subject) => subject.id === subjectId)
  const visible =
    topics.data?.filter((topic) => topic.subject_id === subjectId) || []
  const refresh = () => {
    subjects.refetch()
    topics.refetch()
  }
  return (
    <div className="flex flex-col gap-6">
      <PageHeading
        eyebrow={t("Семейная библиотека")}
        title={
          selected?.name ||
          t("{name}, что изучим сегодня?", { name: displayName })
        }
        description={
          selected
            ? t("Выбери тему для занятия.")
            : t("Выбери предмет, затем тему.")
        }
      />
      <ErrorNotice message={subjects.error || topics.error} retry={refresh} />
      <div className="section-toolbar">
        {subjectId && (
          <Button asChild variant="ghost">
            <a href="#library">
              <ArrowLeft data-icon="inline-start" />
              {t("К предметам")}
            </a>
          </Button>
        )}
        {selected ? (
          <div className="flex flex-wrap gap-2">
            <StudySelection
              key={selected.id}
              topics={visible}
              subjects={subjects.data || []}
            />
            <NameDialog
              title={t("Название предмета")}
              initial={selected.name}
              trigger={
                <Button variant="ghost" aria-label={t("Переименовать предмет")}>
                  <Pencil />
                </Button>
              }
              onSave={async (name) => {
                await api(`/subjects/${selected.id}`, "PATCH", { name })
                refresh()
              }}
            />
            <NameDialog
              title={t("Новая тема")}
              trigger={
                <Button>
                  <Plus data-icon="inline-start" />
                  {t("Добавить тему")}
                </Button>
              }
              onSave={async (name) => {
                const topic = await api<Topic>("/topics", "POST", {
                  name,
                  subject_id: selected.id,
                })
                refresh()
                navigate(`library/topic/${topic.id}`)
              }}
            />
          </div>
        ) : (
          <NameDialog
            title={t("Новый предмет")}
            trigger={
              <Button>
                <Plus data-icon="inline-start" />
                {t("Добавить предмет")}
              </Button>
            }
            onSave={async (name) => {
              const subject = await api<Subject>("/subjects", "POST", { name })
              refresh()
              navigate(`library/subject/${subject.id}`)
            }}
          />
        )}
      </div>
      {subjects.loading || topics.loading ? (
        <Loading />
      ) : subjectId && !selected ? (
        <Blank
          title={t("Предмет не найден")}
          description={t("Выбери предмет в библиотеке.")}
        />
      ) : selected ? (
        visible.length ? (
          <div className="topic-grid">
            {visible.map((topic, index) => (
              <Card key={topic.id}>
                <CardHeader>
                  <div className={`topic-icon tone-${index % 3}`}>
                    <FolderOpen />
                  </div>
                  <CardTitle>
                    <a href={`#library/topic/${topic.id}`}>{topic.name}</a>
                  </CardTitle>
                  <CardDescription>
                    {t("{count} вопросов · {documents} материалов", {
                      count: topic.card_count,
                      documents: topic.document_count,
                    })}
                  </CardDescription>
                </CardHeader>
              </Card>
            ))}
          </div>
        ) : (
          <Blank
            title={t("Добавь первую тему")}
            description={t("В каждой теме будут свои материалы и вопросы.")}
          />
        )
      ) : subjects.data?.length ? (
        <div className="topic-grid">
          {subjects.data.map((subject, index) => (
            <Card key={subject.id}>
              <CardHeader>
                <div className={`topic-icon tone-${index % 3}`}>
                  <BookOpen />
                </div>
                <CardTitle>
                  <a href={`#library/subject/${subject.id}`}>{subject.name}</a>
                </CardTitle>
                <CardDescription>
                  {t("Тем: {count}", { count: subject.topic_count })}
                </CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      ) : (
        <Blank
          title={t("Добавь первый предмет")}
          description={t(
            "Например, история или язык. Затем создай в нём темы."
          )}
        />
      )}
      {selected && (
        <div className="flex flex-wrap gap-3">
          {subjects.data
            ?.filter((subject) => subject.id !== subjectId)
            .map((subject) => (
              <Button key={subject.id} asChild variant="ghost">
                <a href={`#library/subject/${subject.id}`}>{subject.name}</a>
              </Button>
            ))}
        </div>
      )}
    </div>
  )
}
