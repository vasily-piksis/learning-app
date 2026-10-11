import { t, getLocale } from "@/i18n"
import { ArrowRight, Clock, Check, RotateCcw } from "lucide-react"
import { Button } from "@/components/ui/button"
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
import { useQuery } from "@/api"
import type { StudySession } from "@/types"

export default function History() {
  const sessions = useQuery<StudySession[]>("/study")
  const active = sessions.data?.filter((s) => s.status === "active") || [],
    completed = sessions.data?.filter((s) => s.status === "completed") || []
  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        eyebrow={t("Твой собственный темп")}
        title={t("Каждый шаг считается")}
        description={t(
          "Продолжи с того места, где остановилась, или вернись к сложным карточкам."
        )}
      />
      <ErrorNotice message={sessions.error} retry={sessions.refetch} />
      {sessions.loading ? (
        <Loading />
      ) : !sessions.data?.length ? (
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
                  <SessionCard key={value.id} session={value} />
                ))}
              </div>
            </section>
          )}
          {completed.length > 0 && (
            <section className="flex flex-col gap-4">
              <h2>{t("Завершённые занятия")}</h2>
              <div className="history-grid">
                {completed.map((value) => (
                  <SessionCard key={value.id} session={value} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
function SessionCard({ session }: { session: StudySession }) {
  const done = session.status === "completed"
  return (
    <Card>
      <CardHeader>
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
