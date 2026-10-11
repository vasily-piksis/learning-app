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
        eyebrow="Семейная библиотека"
        title={selected?.name || `${displayName}, что изучим сегодня?`}
        description={
          selected ? "Выбери тему для занятия." : "Выбери предмет, затем тему."
        }
      />
      <ErrorNotice message={subjects.error || topics.error} retry={refresh} />
      <div className="section-toolbar">
        {subjectId && (
          <Button asChild variant="ghost">
            <a href="#library">
              <ArrowLeft data-icon="inline-start" />К предметам
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
              title="Название предмета"
              initial={selected.name}
              trigger={
                <Button variant="ghost" aria-label="Переименовать предмет">
                  <Pencil />
                </Button>
              }
              onSave={async (name) => {
                await api(`/subjects/${selected.id}`, "PATCH", { name })
                refresh()
              }}
            />
            <NameDialog
              title="Новая тема"
              trigger={
                <Button>
                  <Plus data-icon="inline-start" />
                  Добавить тему
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
            title="Новый предмет"
            trigger={
              <Button>
                <Plus data-icon="inline-start" />
                Добавить предмет
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
          title="Предмет не найден"
          description="Выбери предмет в библиотеке."
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
                    {topic.card_count} вопросов · {topic.document_count}{" "}
                    материалов
                  </CardDescription>
                </CardHeader>
              </Card>
            ))}
          </div>
        ) : (
          <Blank
            title="Добавь первую тему"
            description="В каждой теме будут свои материалы и вопросы."
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
                <CardDescription>Тем: {subject.topic_count}</CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
      ) : (
        <Blank
          title="Добавь первый предмет"
          description="Например, история или язык. Затем создай в нём темы."
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
