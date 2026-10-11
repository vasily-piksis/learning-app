import { t } from "@/i18n"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
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
import type { Topic, Document, Job } from "@/types"
import Drafts from "./Drafts"

export default function Generation({
  initialTopics,
}: {
  initialTopics: number[]
}) {
  const topics = useQuery<Topic[]>("/topics")
  const id = initialTopics.length === 1 ? initialTopics[0] : null
  const documents = useQuery<Document[]>(
    id ? `/topics/${id}/documents` : null,
    3000
  )
  const [selected, setSelected] = useState<number[] | null>(null),
    [count, setCount] = useState(10),
    [translate, setTranslate] = useState(false),
    [language, setLanguage] = useState("ru"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
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
      const job = await api<Job>("/generate", "POST", {
        topic_ids: [id],
        mode: "quiz",
        count,
        document_ids: ids,
        allow_partial: true,
        target_language: translate ? language : null,
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
                {t("От 1 до 30. Каждый вопрос подходит для флеш-карт и теста.")}
              </FieldDescription>
            </Field>
            <Field orientation="horizontal">
              <Checkbox
                id="translate"
                checked={translate}
                disabled={busy}
                onCheckedChange={(value) => setTranslate(value === true)}
              />
              <FieldLabel htmlFor="translate">
                {t("Перевести вопросы на другой язык")}
              </FieldLabel>
            </Field>
            {translate ? (
              <Field>
                <FieldLabel htmlFor="target-language">
                  {t("Язык перевода")}
                </FieldLabel>
                <Input
                  id="target-language"
                  value={language}
                  onChange={(event) => setLanguage(event.target.value)}
                  pattern="[a-z]{2,3}(-[A-Za-z0-9]{2,8})?"
                  maxLength={20}
                />
                <FieldDescription>
                  {t(
                    "pl — польский, en — английский, ru — русский, lt — литовский."
                  )}
                </FieldDescription>
              </Field>
            ) : (
              <p className="text-sm text-muted-foreground">
                {t("Вопросы будут на языке исходных материалов.")}
              </p>
            )}
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
            !Number.isInteger(count) ||
            count < 1 ||
            count > 30 ||
            (translate && !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$/.test(language))
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
