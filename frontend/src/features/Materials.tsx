import { useState } from "react"
import { Plus, Upload, FileText, Video } from "lucide-react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Field, FieldLabel, FieldDescription } from "@/components/ui/field"
import { Blank, Loading, ErrorNotice, PendingIcon } from "@/components/shared"
import { api, useQuery, errorText } from "@/api"
import type { Topic, Document } from "@/types"
export default function Materials({
  topic,
  refresh,
}: {
  topic: Topic
  refresh: () => void
}) {
  const documents = useQuery<Document[]>(`/topics/${topic.id}/documents`, 3000)
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
  return (
    <div className="flex flex-col gap-6">
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
    </div>
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
  const [tracks, setTracks] = useState<
    { language: string; name: string; is_generated: boolean }[]
  >([])
  const [language, setLanguage] = useState("")
  const [resolvedUrl, setResolvedUrl] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      let selected = language
      if (resolvedUrl !== url.trim()) {
        const result = await api<{
          tracks: typeof tracks
          selected_language: string | null
        }>("/youtube/resolve", "POST", { url: url.trim() })
        setResolvedUrl(url.trim())
        setTracks(result.tracks)
        selected = result.selected_language || ""
        setLanguage(selected)
        if (!selected) return
      }
      if (!selected) return
      const result = await api<Document>(`/topics/${topicId}/youtube`, "POST", {
        url: url.trim(),
        language: selected,
      })
      toast.success(
        result.duplicate
          ? "Это видео уже сохранено в теме"
          : "Видео добавлено. Получаем субтитры"
      )
      setUrl("")
      setTracks([])
      setLanguage("")
      setResolvedUrl("")
      onAdded()
    } catch (error) {
      setError(errorText(error))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Video className="size-5" />
          Урок из YouTube
        </CardTitle>
        <CardDescription>
          Сохраним исходные субтитры без перевода. Вопросы будут ссылаться на
          нужный момент.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => void submit(event)}
        >
          <Field>
            <FieldLabel htmlFor="youtube-url">Ссылка YouTube</FieldLabel>
            <Input
              id="youtube-url"
              type="url"
              value={url}
              disabled={busy}
              onChange={(event) => {
                setUrl(event.target.value)
                setTracks([])
                setLanguage("")
                setResolvedUrl("")
              }}
              placeholder="https://www.youtube.com/watch?v=…"
              maxLength={2048}
              required
            />
          </Field>
          {tracks.length > 0 && (
            <Field>
              <FieldLabel htmlFor="youtube-language">
                Язык исходных субтитров
              </FieldLabel>
              <select
                id="youtube-language"
                className="h-10 rounded-md border bg-background px-3"
                value={language}
                onChange={(event) => setLanguage(event.target.value)}
                disabled={busy}
                required
              >
                <option value="">Выбери дорожку</option>
                {tracks.map((track, index) => (
                  <option key={index} value={track.language}>
                    {track.name} ({track.language})
                    {track.is_generated ? " · auto" : ""}
                  </option>
                ))}
              </select>
              <FieldDescription>
                Не удалось однозначно определить исходный язык. Выбери
                подходящую дорожку.
              </FieldDescription>
            </Field>
          )}
          <ErrorNotice message={error} />
          <Button
            className="self-start"
            disabled={busy || !url.trim() || (tracks.length > 0 && !language)}
          >
            {busy ? <PendingIcon /> : <Plus data-icon="inline-start" />}Добавить
            YouTube
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
