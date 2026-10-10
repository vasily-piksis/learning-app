import { useState } from "react"
import { Layers, Check, FileText } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field"
import { Badge } from "@/components/ui/badge"
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert"
import {
  PageHeading,
  ErrorNotice,
  Loading,
  Blank,
  PendingIcon,
  JobNotice,
  EditCard,
  Sources,
} from "@/components/shared"
import { api, useQuery, errorText, navigate } from "@/api"
import type {
  Topic,
  Subject,
  Document,
  Mode,
  Job,
  Card as StudyCard,
} from "@/types"

export default function Generation({
  initialTopics,
}: {
  initialTopics: number[]
}) {
  const topics = useQuery<Topic[]>("/topics"),
    subjects = useQuery<Subject[]>("/subjects"),
    jobs = useQuery<Job[]>("/jobs", 2500)
  const [selected, setSelected] = useState(initialTopics),
    [mode, setMode] = useState<Mode>("flashcard"),
    [count, setCount] = useState(10),
    [partial, setPartial] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [documents, setDocuments] = useState<Document[] | null>(null),
    [docIds, setDocIds] = useState<number[] | null>(null)
  const initialJob =
    Number(
      new URLSearchParams(window.location.hash.split("?")[1]).get("job")
    ) || null
  const [jobId, setJobId] = useState<number | null>(initialJob)
  const activeJob = useQuery<Job>(
    jobId ? `/jobs/${jobId}` : null,
    jobId ? 2500 : 0
  )
  const validTopics = selected.filter((id) =>
    topics.data?.some((t) => t.id === id)
  )
  async function loadDocuments() {
    setBusy(true)
    setError(null)
    try {
      const lists = await Promise.all(
        validTopics.map((id) => api<Document[]>(`/topics/${id}/documents`))
      )
      const all = lists.flat()
      setDocuments(all)
      setDocIds(all.filter((d) => d.status === "ready").map((d) => d.id))
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  async function generate() {
    setBusy(true)
    setError(null)
    try {
      const job = await api<Job>("/generate", "POST", {
        topic_ids: validTopics,
        mode,
        count,
        allow_partial: partial,
        document_ids: docIds,
      })
      setJobId(job.id)
      jobs.refetch()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        eyebrow="Материалы становятся карточками"
        title="Что повторим?"
        description="Выбери темы. Каждый вопрос будет опираться только на их материалы."
      />
      <div className="generation-layout">
        <Card>
          <CardHeader>
            <CardTitle className="text-xl">Собери свой набор</CardTitle>
            <CardDescription>
              Одна тема или несколько — решаешь ты.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <ErrorNotice
              message={topics.error || subjects.error}
              retry={() => {
                topics.refetch()
                subjects.refetch()
              }}
            />
            {topics.loading ? (
              <Loading />
            ) : topics.data?.length ? (
              <FieldGroup>
                <Field>
                  <FieldLabel>1. Выбери темы</FieldLabel>
                  <div className="topic-options">
                    {topics.data.map((topic) => (
                      <label
                        key={topic.id}
                        className={
                          selected.includes(topic.id)
                            ? "topic-option selected"
                            : "topic-option"
                        }
                      >
                        <Checkbox
                          checked={selected.includes(topic.id)}
                          onCheckedChange={(checked) => {
                            setSelected((v) =>
                              checked
                                ? [...v, topic.id]
                                : v.filter((id) => id !== topic.id)
                            )
                            setDocuments(null)
                            setDocIds(null)
                          }}
                        />
                        <span>
                          <strong>{topic.name}</strong>
                          <small>
                            {
                              subjects.data?.find(
                                (s) => s.id === topic.subject_id
                              )?.name
                            }{" "}
                            · {topic.document_count} материалов
                          </small>
                        </span>
                      </label>
                    ))}
                  </div>
                </Field>
              </FieldGroup>
            ) : (
              <Blank
                title="Сначала добавь тему"
                description="Создай предмет и загрузи материалы в библиотеку."
                action={
                  <Button asChild>
                    <a href="#library">В библиотеку</a>
                  </Button>
                }
              />
            )}
            <FieldGroup>
              <Field>
                <FieldLabel>2. Формат</FieldLabel>
                <div className="format-switch">
                  {(["flashcard", "quiz"] as const).map((value) => (
                    <Button
                      key={value}
                      variant={mode === value ? "default" : "outline"}
                      aria-pressed={mode === value}
                      onClick={() => setMode(value)}
                    >
                      {value === "flashcard"
                        ? "Флеш-карты"
                        : "Тест с вариантами"}
                    </Button>
                  ))}
                </div>
                <FieldDescription>
                  {mode === "flashcard"
                    ? "Вспомни ответ, открой карточку и оцени себя."
                    : "Выбери вариант — правильный ответ появится после проверки."}
                </FieldDescription>
              </Field>
              <Field>
                <FieldLabel htmlFor="count">3. Сколько карточек?</FieldLabel>
                <Input
                  className="max-w-32"
                  id="count"
                  type="number"
                  min={Math.max(1, validTopics.length)}
                  max={30}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                />
                <FieldDescription>
                  От {Math.max(1, validTopics.length)} до 30. На каждую тему —
                  хотя бы один вопрос.
                </FieldDescription>
              </Field>
              <Field orientation="horizontal">
                <Checkbox
                  id="partial"
                  checked={partial}
                  onCheckedChange={(v) => setPartial(v === true)}
                />
                <FieldLabel htmlFor="partial">
                  Можно использовать только готовые материалы
                </FieldLabel>
              </Field>
            </FieldGroup>
            {validTopics.length > 0 && (
              <Button
                variant="outline"
                onClick={() => void loadDocuments()}
                disabled={busy}
              >
                <FileText data-icon="inline-start" />
                Выбрать отдельные документы
              </Button>
            )}
            {documents && (
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  Отмеченные документы ограничивают материалы генерации.
                </p>
                {documents.map((d) => (
                  <label key={d.id} className="flex items-center gap-3 text-sm">
                    <Checkbox
                      checked={docIds?.includes(d.id)}
                      disabled={d.status !== "ready"}
                      onCheckedChange={(v) =>
                        setDocIds((ids) =>
                          v
                            ? [...(ids || []), d.id]
                            : (ids || []).filter((id) => id !== d.id)
                        )
                      }
                    />
                    <span className="break-words">
                      {d.name} · {d.status === "ready" ? "готов" : "не готов"}
                    </span>
                  </label>
                ))}
                <Button
                  variant="ghost"
                  onClick={() => {
                    setDocuments(null)
                    setDocIds(null)
                  }}
                >
                  Использовать все документы тем
                </Button>
              </div>
            )}
            <ErrorNotice message={error} />
          </CardContent>
          <CardFooter>
            <Button
              className="w-full"
              onClick={() => void generate()}
              disabled={
                busy ||
                !validTopics.length ||
                count < validTopics.length ||
                count > 30 ||
                count < 1 ||
                !!topics.error ||
                (docIds !== null && !docIds.length)
              }
            >
              {busy ? <PendingIcon /> : <Layers data-icon="inline-start" />}
              Создать карточки
            </Button>
          </CardFooter>
        </Card>
        <div className="flex flex-col gap-6">
          <Alert>
            <Layers />
            <AlertTitle>Сначала проверим вопросы</AlertTitle>
            <AlertDescription>
              Новый набор сохранится как черновик. Ты сможешь поправить
              формулировки и выбрать карточки для занятий.
            </AlertDescription>
          </Alert>
          <ErrorNotice message={activeJob.error} retry={activeJob.refetch} />
          {activeJob.data && (
            <>
              <JobNotice
                job={activeJob.data}
                retry={async () => {
                  try {
                    await api(`/jobs/${jobId}/retry`, "POST")
                    activeJob.refetch()
                  } catch (e) {
                    setError(errorText(e))
                  }
                }}
              />
              {activeJob.data.status === "succeeded" && (
                <Drafts key={jobId} job={activeJob.data} />
              )}
            </>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Твои наборы</CardTitle>
              <CardDescription>
                Результаты останутся здесь, даже если закрыть страницу.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ErrorNotice message={jobs.error} retry={jobs.refetch} />
              {jobs.data?.filter((j) => j.kind === "generate").length ? (
                <div className="flex flex-col gap-2">
                  {jobs.data
                    .filter((j) => j.kind === "generate")
                    .map((job) => (
                      <Button
                        key={job.id}
                        variant={job.id === jobId ? "secondary" : "ghost"}
                        className="justify-between"
                        onClick={() => setJobId(job.id)}
                      >
                        <span>Набор #{job.id}</span>
                        <Badge variant="outline">
                          {
                            (
                              {
                                succeeded: "Готов",
                                failed: "Ошибка",
                                running: "Готовим",
                                queued: "В очереди",
                              } as Record<string, string>
                            )[job.status]
                          }
                        </Badge>
                      </Button>
                    ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  Пока нет наборов. Начнём с одной темы?
                </p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
function Drafts({ job }: { job: Job }) {
  const cards = useQuery<StudyCard[]>(`/cards?job_id=${job.id}`),
    [selected, setSelected] = useState<number[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const drafts = cards.data?.filter((c) => c.status === "draft") || []
  return (
    <div className="flex flex-col gap-4">
      <div className="section-toolbar">
        <h2>Проверим карточки</h2>
        <Button
          variant="ghost"
          disabled={!drafts.length}
          onClick={() => setSelected(drafts.map((c) => c.id))}
        >
          Выбрать все
        </Button>
      </div>
      {job.result?.warnings?.map((warning, i) => (
        <Alert key={i}>
          <AlertTitle>Материалов оказалось меньше</AlertTitle>
          <AlertDescription>{warning}</AlertDescription>
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
                    aria-label={`Выбрать: ${card.question}`}
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
                  <Badge variant="secondary">Сохранена</Badge>
                )}
                <CardTitle>{card.question}</CardTitle>
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <p className="whitespace-pre-wrap">{card.answer}</p>
              {card.mode === "quiz" && (
                <ol className="flex flex-col gap-2">
                  {card.options.map((v, i) => (
                    <li key={i} className="flex items-center gap-2">
                      {i === card.correct_index && (
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
            </CardFooter>
          </Card>
        ))
      ) : (
        <Blank
          title="Карточки не созданы"
          description="Попробуй добавить материалы или запросить меньше вопросов."
        />
      )}
      {drafts.length > 0 && (
        <Button
          disabled={busy || !selected.length}
          onClick={async () => {
            setBusy(true)
            try {
              await api("/cards/save", "POST", { card_ids: selected })
              toast.success("Карточки сохранены в темах")
              setSelected([])
              cards.refetch()
            } catch (e) {
              setError(errorText(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy && <PendingIcon />}Сохранить выбранные ({selected.length})
        </Button>
      )}
      {cards.data?.some((c) => c.status === "saved") && (
        <Button variant="outline" onClick={() => navigate("library")}>
          Перейти к занятиям
        </Button>
      )}
    </div>
  )
}
