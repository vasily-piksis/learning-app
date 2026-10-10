import { useState } from "react"
import {
  BookOpen,
  Plus,
  ArrowUpRight,
  ArrowLeft,
  FileText,
  Upload,
  Layers,
  Play,
  Pencil,
  FolderOpen,
  Video,
} from "lucide-react"
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
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field"
import { Separator } from "@/components/ui/separator"
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
import {
  PageHeading,
  NameDialog,
  Blank,
  Loading,
  ErrorNotice,
  EditCard,
  Sources,
  PendingIcon,
} from "@/components/shared"
import { api, useQuery, errorText, navigate } from "@/api"
import type {
  Subject,
  Topic,
  Document,
  Card as StudyCard,
  StudySession,
} from "@/types"

export default function Library({
  subjectId,
  topicId,
  displayName,
}: {
  subjectId?: number
  topicId?: number
  displayName: string
}) {
  const subjects = useQuery<Subject[]>("/subjects"),
    topics = useQuery<Topic[]>("/topics")
  const selectedTopic = topics.data?.find((t) => t.id === topicId),
    selectedSubject = subjects.data?.find(
      (s) => s.id === (subjectId || selectedTopic?.subject_id)
    )
  const visible = selectedSubject
    ? topics.data?.filter((t) => t.subject_id === selectedSubject.id)
    : topics.data
  const refresh = () => {
    subjects.refetch()
    topics.refetch()
  }
  const newSubject = (
    <NameDialog
      title="Новый предмет"
      trigger={
        <Button variant="outline">
          <Plus data-icon="inline-start" />
          Добавить предмет
        </Button>
      }
      onSave={async (name) => {
        const value = await api<Subject>("/subjects", "POST", { name })
        refresh()
        navigate(`library/subject/${value.id}`)
      }}
    />
  )
  return (
    <div className="flex flex-col gap-8">
      <PageHeading
        eyebrow="Твоя семейная библиотека"
        title={
          selectedTopic?.name ||
          selectedSubject?.name ||
          `${displayName}, что изучим сегодня?`
        }
        description={
          selectedTopic
            ? "Материалы и карточки одной темы. Можно добавлять новые файлы в любое время."
            : selectedSubject
              ? "Большой предмет — маленькими, понятными шагами. Выбери тему."
              : "Все учебные материалы на своём месте. Выбери тему и начни с одной карточки."
        }
        action={
          selectedTopic ? (
            <Button asChild>
              <a href={`#generate?topics=${topicId}`}>
                <Layers data-icon="inline-start" />
                Создать карточки
              </a>
            </Button>
          ) : (
            <div className="flex flex-wrap gap-2">
              <StudySelection
                key={selectedSubject?.id || "all"}
                topics={visible || []}
                subjects={subjects.data || []}
              />
              {newSubject}
            </div>
          )
        }
      />
      <ErrorNotice message={subjects.error || topics.error} retry={refresh} />
      {topics.loading || subjects.loading ? (
        <Loading />
      ) : (
        <div className="library-layout">
          <aside className="library-sidebar">
            <div className="sidebar-label">
              ПРЕДМЕТЫ <span>{subjects.data?.length || 0}</span>
            </div>
            <a
              href="#library"
              className={
                !selectedSubject ? "sidebar-link active" : "sidebar-link"
              }
            >
              <LibraryIcon />
              Все предметы
            </a>
            {subjects.data?.map((subject) => (
              <a
                key={subject.id}
                href={`#library/subject/${subject.id}`}
                className={
                  selectedSubject?.id === subject.id
                    ? "sidebar-link active"
                    : "sidebar-link"
                }
              >
                <BookOpen className="size-4 shrink-0" />
                <span>{subject.name}</span>
                <span className="sidebar-count">{subject.topic_count}</span>
              </a>
            ))}
            <Separator />
            <div className="sidebar-note">
              <BookOpen className="size-5" />
              <strong>Только нужная тема</strong>
              <p>Карточки создаются по тем материалам, которые ты выбираешь.</p>
            </div>
          </aside>
          <section className="library-body">
            {selectedTopic ? (
              <TopicView
                key={topicId}
                topic={selectedTopic}
                refresh={refresh}
              />
            ) : (
              <>
                <div className="section-toolbar">
                  <h2>
                    {selectedSubject ? "Темы предмета" : "Темы для изучения"}
                  </h2>
                  {selectedSubject && (
                    <div className="flex flex-wrap gap-2">
                      <NameDialog
                        title="Название предмета"
                        initial={selectedSubject.name}
                        trigger={
                          <Button
                            variant="ghost"
                            aria-label="Переименовать предмет"
                          >
                            <Pencil />
                          </Button>
                        }
                        onSave={async (name) => {
                          await api(
                            `/subjects/${selectedSubject.id}`,
                            "PATCH",
                            { name }
                          )
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
                          await api("/topics", "POST", {
                            name,
                            subject_id: selectedSubject.id,
                          })
                          refresh()
                        }}
                      />
                    </div>
                  )}
                </div>
                {visible?.length ? (
                  <div className="topic-grid">
                    {visible.map((topic, i) => (
                      <Card key={topic.id} className="topic-card">
                        <CardHeader>
                          <div className={`topic-icon tone-${i % 3}`}>
                            <FolderOpen />
                          </div>
                          <CardTitle className="text-lg">
                            <a href={`#library/topic/${topic.id}`}>
                              {topic.name}
                            </a>
                          </CardTitle>
                          <CardDescription>
                            {
                              subjects.data?.find(
                                (s) => s.id === topic.subject_id
                              )?.name
                            }
                          </CardDescription>
                        </CardHeader>
                        <CardContent className="flex flex-wrap gap-2">
                          <Badge variant="secondary">
                            {topic.document_count} материалов
                          </Badge>
                          <Badge variant="outline">
                            {topic.card_count} карточек
                          </Badge>
                        </CardContent>
                        <CardFooter>
                          <Button variant="ghost" asChild>
                            <a href={`#library/topic/${topic.id}`}>
                              Открыть тему
                              <ArrowUpRight data-icon="inline-end" />
                            </a>
                          </Button>
                        </CardFooter>
                      </Card>
                    ))}
                  </div>
                ) : (
                  <Blank
                    title={
                      selectedSubject
                        ? "Первая тема — первый шаг"
                        : "Здесь начнётся твоя библиотека"
                    }
                    description={
                      selectedSubject
                        ? "Добавь тему, например «Древний Египет», и загрузи страницы учебника."
                        : "Создай предмет — историю, биологию или любой другой. Потом добавь темы и материалы."
                    }
                    action={!selectedSubject ? newSubject : undefined}
                  />
                )}
              </>
            )}
          </section>
        </div>
      )}
    </div>
  )
}
function LibraryIcon() {
  return <Layers className="size-4 shrink-0" />
}
function TopicView({ topic, refresh }: { topic: Topic; refresh: () => void }) {
  const documents = useQuery<Document[]>(`/topics/${topic.id}/documents`, 3000),
    cards = useQuery<StudyCard[]>(`/cards?topic_id=${topic.id}`)
  const [files, setFiles] = useState<File[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  async function upload() {
    setBusy(true)
    setError(null)
    const failed: File[] = []
    for (const file of files) {
      const body = new FormData()
      body.append("file", file)
      try {
        await api(`/topics/${topic.id}/documents`, "POST", body)
        toast.success(`${file.name} сохранён`)
      } catch (e) {
        failed.push(file)
        setError(errorText(e))
      }
    }
    setFiles(failed)
    setBusy(false)
    documents.refetch()
    refresh()
  }
  async function start(mode: "flashcard" | "quiz") {
    setBusy(true)
    setError(null)
    try {
      const session = await api<StudySession>("/study", "POST", {
        topic_ids: [topic.id],
        mode,
      })
      navigate(`study/${session.id}`)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const saved = cards.data?.filter((c) => c.status === "saved") || [],
    drafts = cards.data?.filter((c) => c.status === "draft") || []
  return (
    <div className="flex flex-col gap-6">
      <div className="section-toolbar">
        <Button variant="ghost" asChild>
          <a href={`#library/subject/${topic.subject_id}`}>
            <ArrowLeft data-icon="inline-start" />К темам
          </a>
        </Button>
        <NameDialog
          title="Название темы"
          initial={topic.name}
          trigger={
            <Button variant="ghost">
              <Pencil data-icon="inline-start" />
              Переименовать
            </Button>
          }
          onSave={async (name) => {
            await api(`/topics/${topic.id}`, "PATCH", { name })
            refresh()
          }}
        />
      </div>
      <Card>
        <CardHeader>
          <CardTitle>Добавить материалы</CardTitle>
          <CardDescription>
            Учебник, конспект или фотографии страниц.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <Field>
            <FieldLabel htmlFor="files">Выбрать PDF или фотографии</FieldLabel>
            <Input
              id="files"
              type="file"
              multiple
              accept="application/pdf,image/jpeg,image/png,image/webp"
              disabled={busy}
              onChange={(e) => setFiles(Array.from(e.target.files || []))}
            />
            <FieldDescription>
              PDF, JPEG, PNG, WebP · до 20 МБ · до 50 страниц в PDF
            </FieldDescription>
          </Field>
          {files.length > 0 && (
            <>
              <p className="text-sm break-words">
                {files.map((f) => f.name).join(", ")}
              </p>
              <Button
                onClick={() => void upload()}
                disabled={busy}
                className="self-start"
              >
                {busy ? <PendingIcon /> : <Upload data-icon="inline-start" />}
                Загрузить {files.length} файлов
              </Button>
            </>
          )}
          <ErrorNotice message={error} />
        </CardContent>
      </Card>
      <YouTubeImport
        topicId={topic.id}
        onAdded={() => {
          documents.refetch()
          refresh()
        }}
      />
      <div className="section-toolbar">
        <h2>
          Материалы{" "}
          <span className="muted-count">{documents.data?.length || 0}</span>
        </h2>
        <Badge variant="outline">Версия {topic.version}</Badge>
      </div>
      <ErrorNotice message={documents.error} retry={documents.refetch} />
      {documents.loading ? (
        <Loading />
      ) : documents.data?.length ? (
        <div className="document-list">
          {documents.data.map((document) => (
            <div key={document.id} className="document-row">
              <div className="document-icon">
                {document.source_url ? <Video /> : <FileText />}
              </div>
              <div className="document-details">
                <a
                  href={
                    document.source_url ||
                    `/api/documents/${document.id}/download`
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  {document.name}
                </a>
                <p>
                  {document.source_url
                    ? `Субтитры: ${document.language} · ${document.page_count} фрагментов`
                    : `${document.page_count} стр.`}{" "}
                  · {(document.size / 1024 / 1024).toFixed(1)} МБ
                </p>
                {document.source_url && document.status === "ready" && (
                  <a
                    className="text-sm"
                    href={`/api/documents/${document.id}/download`}
                  >
                    Скачать сохранённые субтитры
                  </a>
                )}
                {document.error && (
                  <p className="text-destructive">{document.error}</p>
                )}
                {document.warnings?.map((warning) => (
                  <p key={warning.page} className="text-muted-foreground">
                    {document.source_url ? "Фрагмент" : "Стр."} {warning.page}:{" "}
                    {warning.messages.join("; ")}
                  </p>
                ))}
              </div>
              <div className="flex shrink-0 flex-col items-end gap-2">
                <Badge
                  variant={
                    document.status === "failed"
                      ? "destructive"
                      : document.status === "ready"
                        ? "secondary"
                        : "outline"
                  }
                >
                  {
                    (
                      {
                        ready: "Готово",
                        queued: "В очереди",
                        processing: document.source_url
                          ? "Получаем субтитры"
                          : "Распознаём",
                        failed: "Ошибка",
                      } as Record<string, string>
                    )[document.status]
                  }
                </Badge>
                {document.status === "failed" && (
                  <Button
                    variant="outline"
                    onClick={async () => {
                      try {
                        await api(`/jobs/${document.job_id}/retry`, "POST")
                        documents.refetch()
                      } catch (e) {
                        setError(errorText(e))
                      }
                    }}
                  >
                    Повторить
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Blank
          title="Добавь страницы учебника"
          description="Материалы останутся в этой теме. Новые файлы можно добавлять позже."
        />
      )}
      <div className="section-toolbar">
        <h2>
          Карточки <span className="muted-count">{saved.length}</span>
        </h2>
        <div className="flex flex-wrap gap-2">
          {(["flashcard", "quiz"] as const).map((mode) => (
            <Button
              key={mode}
              variant={mode === "flashcard" ? "default" : "outline"}
              disabled={
                busy ||
                !saved.some((c) => mode === "flashcard" || c.mode === "quiz")
              }
              onClick={() => void start(mode)}
            >
              <Play data-icon="inline-start" />
              {mode === "flashcard" ? "Повторить" : "Пройти тест"}
            </Button>
          ))}
        </div>
      </div>
      <ErrorNotice message={cards.error} retry={cards.refetch} />
      {cards.loading ? (
        <Loading />
      ) : saved.length ? (
        <div className="flex flex-col gap-4">
          {saved.map((card) => (
            <Card key={card.id}>
              <CardHeader>
                <CardTitle>{card.question}</CardTitle>
                <CardDescription>
                  {card.mode === "quiz" ? "Тест" : "Флеш-карта"}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <p className="whitespace-pre-wrap">{card.answer}</p>
                <Sources sources={card.sources} />
              </CardContent>
              <CardFooter>
                <EditCard card={card} onSaved={cards.refetch} />
              </CardFooter>
            </Card>
          ))}
        </div>
      ) : (
        <Blank
          title="Из материалов — в знания"
          description="Создай карточки по этой теме, проверь вопросы и сохрани те, которые хочешь повторять."
          action={
            <Button asChild>
              <a href={`#generate?topics=${topic.id}`}>
                <Layers data-icon="inline-start" />
                Создать карточки
              </a>
            </Button>
          }
        />
      )}{" "}
      {drafts.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Черновики: {drafts.length}</CardTitle>
            <CardDescription>
              Вопросы ждут твоей проверки и выбора.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {Array.from(
              new Set(
                drafts.map((c) => (c as StudyCard & { job_id?: number }).job_id)
              )
            )
              .filter(Boolean)
              .map((id) => (
                <Button key={id} asChild variant="outline">
                  <a href={`#generate?job=${id}`}>Проверить набор #{id}</a>
                </Button>
              ))}
            <Button asChild variant="outline">
              <a href="#generate">Открыть готовые наборы</a>
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function StudySelection({
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
          Выбрать темы для повторения
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Что повторим?</DialogTitle>
          <DialogDescription>
            Выбери одну или несколько тем. Флеш-карты используют все сохранённые
            вопросы, тест — только вопросы с вариантами ответа.
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
            aria-label="Формат занятия"
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
                {value === "quiz" ? "Тест" : "Флеш-карты"}
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
                const session = await api<StudySession>("/study", "POST", {
                  topic_ids: chosen,
                  mode,
                })
                navigate(`study/${session.id}`)
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy && <PendingIcon />}Начать занятие
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function YouTubeImport({
  topicId,
  onAdded,
}: {
  topicId: number
  onAdded: () => void
}) {
  const [url, setUrl] = useState("")
  const [language, setLanguage] = useState("ru")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Video className="size-5" />
          Урок из YouTube
        </CardTitle>
        <CardDescription>
          Сохраним субтитры видео в эту тему. Карточки будут ссылаться на нужный
          момент урока.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={async (event) => {
            event.preventDefault()
            if (busy || !url.trim() || !language.trim()) return
            setBusy(true)
            setError(null)
            try {
              await api(`/topics/${topicId}/youtube`, "POST", {
                url: url.trim(),
                language: language.trim(),
              })
              setUrl("")
              toast.success("Видео добавлено. Получаем субтитры")
              onAdded()
            } catch (e) {
              setError(errorText(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          <Field>
            <FieldLabel htmlFor="youtube-url">Ссылка YouTube</FieldLabel>
            <Input
              id="youtube-url"
              type="url"
              value={url}
              disabled={busy}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://www.youtube.com/watch?v=…"
              maxLength={2048}
              required
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="youtube-language">Язык субтитров</FieldLabel>
            <Input
              id="youtube-language"
              className="max-w-40"
              value={language}
              disabled={busy}
              onChange={(event) => setLanguage(event.target.value)}
              maxLength={20}
              required
              pattern="[a-z]{2,3}(-[A-Za-z0-9]{2,8})?"
            />
            <FieldDescription>
              ru — русский, en — английский, lt — литовский. Получим субтитры
              только на выбранном языке. Автоматические субтитры могут содержать
              ошибки; YouTube иногда ограничивает получение с сервера.
            </FieldDescription>
          </Field>
          <ErrorNotice message={error} />
          <Button
            className="self-start"
            disabled={busy || !url.trim() || !language.trim()}
          >
            {busy ? <PendingIcon /> : <Plus data-icon="inline-start" />}Добавить
            YouTube
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
