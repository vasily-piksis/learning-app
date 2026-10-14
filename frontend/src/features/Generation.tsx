import { t } from "@/i18n"
import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group"
import { questionTypes, questionLabel } from "@/lib/exercises"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
  FieldSet,
  FieldLegend,
} from "@/components/ui/field"
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
  PendingIcon,
  JobNotice,
  PageHeading,
} from "@/components/shared"
import { api, useQuery, errorText, navigate } from "@/api"
import type { Topic, Document, Job, QuestionType } from "@/types"
import Drafts from "./Drafts"

export default function Generation({
  initialTopics,
  initialMethod,
}: {
  initialTopics: number[]
  initialMethod?: string
}) {
  const topics = useQuery<Topic[]>("/topics")
  const id = initialTopics.length === 1 ? initialTopics[0] : null
  const documents = useQuery<Document[]>(
    id ? `/topics/${id}/documents` : null,
    3000
  )
  const [selected, setSelected] = useState<number[] | null>(null),
    [count, setCount] = useState(10),
    [practiceGoal, setPracticeGoal] = useState<"content" | "language">(
      initialMethod === "ending" || initialMethod === "ordering"
        ? "language"
        : "content"
    ),
    [selectedTypes, setSelectedTypes] = useState<QuestionType[]>([
      questionTypes.find((type) => type === initialMethod) || "choice",
    ]),
    [goalNotice, setGoalNotice] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const requestKey = useRef<{ signature: string; key: string } | null>(null)
  const mode = initialMethod === "flashcard" ? "flashcard" : "quiz"
  const allowedTypes =
    practiceGoal === "language"
      ? questionTypes
      : questionTypes.filter((type) => type !== "ending" && type !== "ordering")
  const available =
    documents.data?.filter((document) => document.status === "ready") || []
  const newIds = available
    .filter((document) => !document.used_for_questions)
    .map((document) => document.id)
  const ids =
    selected ||
    (newIds.length ? newIds : available.map((document) => document.id))
  async function generate() {
    setBusy(true)
    setError(null)
    try {
      const body = {
        topic_ids: [id],
        mode,
        count,
        document_ids: ids,
        allow_partial: true,
        question_types: selectedTypes,
        practice_goal: practiceGoal,
      }
      const signature = JSON.stringify(body)
      if (requestKey.current?.signature !== signature)
        requestKey.current = { signature, key: crypto.randomUUID() }
      const job = await api<Job>("/generate", "POST", {
        ...body,
        idempotency_key: requestKey.current.key,
      })
      navigate(`generation/${job.id}`)
    } catch (error) {
      setError(errorText(error))
    } finally {
      setBusy(false)
    }
  }
  if (!id)
    return (
      <div className="flex flex-col gap-4">
        <PageHeading
          eyebrow={t("Вопросы")}
          title={t("Выбери тему")}
          description={t(
            "Создание вопросов открывается внутри конкретной темы."
          )}
        />
        {topics.loading ? (
          <Loading />
        ) : (
          topics.data?.map((topic) => (
            <Button key={topic.id} variant="outline" asChild>
              <a href={`#library/topic/${topic.id}/create`}>{topic.name}</a>
            </Button>
          ))
        )}
        <Button asChild variant="ghost">
          <a href="#library">{t("В библиотеку")}</a>
        </Button>
      </div>
    )
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("Создать вопросы")}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <ErrorNotice
          message={documents.error || error}
          retry={documents.refetch}
        />
        {documents.loading ? (
          <Loading />
        ) : available.length ? (
          <FieldGroup>
            <Field>
              <FieldLabel>{t("Материалы для вопросов")}</FieldLabel>
              <FieldDescription>
                {t(
                  "Сначала выбраны новые материалы. Можно выбрать другие или использовать все готовые."
                )}
              </FieldDescription>
              {available.map((document) => (
                <label key={document.id} className="flex items-start gap-3">
                  <Checkbox
                    checked={ids.includes(document.id)}
                    disabled={busy}
                    onCheckedChange={(checked) =>
                      setSelected(
                        checked
                          ? [...ids, document.id]
                          : ids.filter((id) => id !== document.id)
                      )
                    }
                  />
                  <span className="break-words">
                    {document.name}
                    {!document.used_for_questions && (
                      <small className="block text-muted-foreground">
                        {t("Новый материал")}
                      </small>
                    )}
                  </span>
                </label>
              ))}
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  setSelected(available.map((document) => document.id))
                }
              >
                {t("Выбрать все готовые")}
              </Button>
            </Field>
            <Field>
              <FieldLabel htmlFor="count">{t("Сколько вопросов?")}</FieldLabel>
              <Input
                id="count"
                type="number"
                min={1}
                max={30}
                value={count}
                disabled={busy}
                onChange={(event) => setCount(Number(event.target.value))}
              />
              <FieldDescription>
                {t("От 1 до 30. Общее количество для всех выбранных типов.")}
              </FieldDescription>
            </Field>
            {mode === "quiz" && (
              <>
                <FieldSet>
                  <FieldLegend>{t("Что тренируем?")}</FieldLegend>
                  <ToggleGroup
                    type="single"
                    variant="outline"
                    value={practiceGoal}
                    disabled={busy}
                    onValueChange={(value) => {
                      if (value !== "content" && value !== "language") return
                      setPracticeGoal(value)
                      if (
                        value === "content" &&
                        selectedTypes.some(
                          (type) => type === "ending" || type === "ordering"
                        )
                      ) {
                        const compatible = selectedTypes.filter(
                          (type) => type !== "ending" && type !== "ordering"
                        )
                        setSelectedTypes(
                          compatible.length ? compatible : ["choice"]
                        )
                        setGoalNotice(true)
                      } else setGoalNotice(false)
                    }}
                  >
                    <ToggleGroupItem value="content">
                      {t("Содержание темы")}
                    </ToggleGroupItem>
                    <ToggleGroupItem value="language">
                      {t("Язык и грамматику")}
                    </ToggleGroupItem>
                  </ToggleGroup>
                  {goalNotice && (
                    <FieldDescription>
                      {t(
                        "Окончания и сборка предложения доступны для языковой практики."
                      )}
                    </FieldDescription>
                  )}
                </FieldSet>
                <FieldSet>
                  <FieldLegend>{t("Типы вопросов")}</FieldLegend>
                  <ToggleGroup
                    type="multiple"
                    variant="outline"
                    value={selectedTypes}
                    disabled={busy}
                    className="flex-wrap"
                    onValueChange={(types) =>
                      setSelectedTypes(types as QuestionType[])
                    }
                  >
                    {allowedTypes.map((type) => (
                      <ToggleGroupItem key={type} value={type}>
                        {questionLabel(type)}
                      </ToggleGroupItem>
                    ))}
                  </ToggleGroup>
                  <FieldDescription>
                    {t(
                      "Количество общее для выбранных типов; неподходящие задания не будут созданы."
                    )}
                  </FieldDescription>
                </FieldSet>
              </>
            )}
            <p className="text-sm text-muted-foreground">
              {t("Вопросы будут на языке исходных материалов.")}
            </p>
          </FieldGroup>
        ) : (
          <Blank
            title={t("Нужны готовые материалы")}
            description={t("Добавь материал или дождись обработки.")}
            action={
              <Button asChild>
                <a href={`#library/topic/${id}/materials`}>
                  {t("К материалам")}
                </a>
              </Button>
            }
          />
        )}
      </CardContent>
      <CardFooter>
        <Button
          disabled={
            busy ||
            !ids.length ||
            !selectedTypes.length ||
            count < selectedTypes.length ||
            !Number.isInteger(count) ||
            count < 1 ||
            count > 30
          }
          onClick={() => void generate()}
        >
          {busy && <PendingIcon />}
          {t("Создать вопросы")}
        </Button>
      </CardFooter>
    </Card>
  )
}

export function GenerationResult({ id }: { id: number }) {
  const job = useQuery<Job>(`/jobs/${id}`, 1500)
  const [error, setError] = useState<string | null>(null)
  const topicId =
    job.data?.topic_ids?.length === 1 ? job.data.topic_ids[0] : null
  return (
    <div className="flex flex-col gap-6">
      <PageHeading
        eyebrow={t("Вопросы")}
        title={
          job.data?.status === "succeeded"
            ? t("Проверь новые вопросы")
            : t("Создаём вопросы")
        }
        description={t("Результат сохраняется после закрытия страницы.")}
      />
      <Button variant="ghost" asChild>
        <a href={topicId ? `#library/topic/${topicId}` : "#library"}>
          {t("К теме")}
        </a>
      </Button>
      <ErrorNotice message={job.error || error} retry={job.refetch} />
      {job.loading ? (
        <Loading />
      ) : job.data?.status === "succeeded" ? (
        <Drafts job={job.data} />
      ) : (
        job.data && (
          <JobNotice
            job={job.data}
            retry={() =>
              void api(`/jobs/${id}/retry`, "POST")
                .then(job.refetch)
                .catch((error) => setError(errorText(error)))
            }
          />
        )
      )}
    </div>
  )
}
