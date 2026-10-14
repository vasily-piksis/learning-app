import { useRef, useState } from "react"
import { RefreshCw } from "lucide-react"
import { t } from "@/i18n"
import { api, useQuery, errorText, APIError } from "@/api"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import {
  ErrorNotice,
  JobNotice,
  PendingIcon,
  Sources,
} from "@/components/shared"
import type {
  Card,
  FullExercise,
  Job,
  QuestionCandidate,
  ImageUpdates,
} from "@/types"
import { exerciseSolution } from "@/lib/exercises"
import EditQuestion from "./EditQuestion"
import ExerciseSolution from "./ExerciseSolution"
import QuestionImages, { QuestionImageView } from "./QuestionImages"
export default function RegenerateQuestion({
  card,
  onSaved,
}: {
  card: Card
  onSaved: () => void
}) {
  const [open, setOpen] = useState(false),
    [jobId, setJobId] = useState<number | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [locked, setLocked] = useState(false)
  const [edited, setEdited] = useState<{
    jobId: number
    candidate: QuestionCandidate
  } | null>(null)
  const [imageUpdates, setImageUpdates] = useState<ImageUpdates>({})
  const [imageBusy, setImageBusy] = useState(false)
  const request = useRef({
    version: card.version,
    idempotency_key: crypto.randomUUID(),
    another_variant: false,
  })
  const applyRequest = useRef<{
    candidate: QuestionCandidate
    image_updates?: ImageUpdates
  } | null>(null)
  const job = useQuery<Job>(
    jobId ? `/jobs/${jobId}` : null,
    open && jobId ? 1000 : 0
  )
  const candidate =
    edited?.jobId === jobId ? edited.candidate : job.data?.result?.candidate
  async function start(another = false) {
    if (another || request.current.version !== card.version)
      request.current = {
        version: card.version,
        idempotency_key: crypto.randomUUID(),
        another_variant: another,
      }
    setOpen(true)
    setBusy(true)
    setError(null)
    try {
      const result = await api<Job>(
        `/cards/${card.id}/regenerate`,
        "POST",
        request.current
      )
      setJobId(result.id)
      if (another || result.id !== jobId) {
        setEdited(null)
        setImageUpdates({})
      }
      applyRequest.current = null
      setLocked(false)
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const preview = candidate
    ? {
        ...card,
        ...candidate,
        version: job.data?.result?.base_version || card.version,
        status: "draft",
      }
    : null
  return (
    <>
      <Button
        variant="ghost"
        aria-label={t("Перегенерировать вопрос")}
        onClick={() => void start()}
        disabled={busy || imageBusy}
      >
        <RefreshCw data-icon="inline-start" />
        {t("Перегенерировать")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!busy && !imageBusy) setOpen(next)
        }}
      >
        <DialogContent
          className="max-h-[90dvh] overflow-y-auto"
          showCloseButton={!busy && !imageBusy}
        >
          <DialogHeader>
            <DialogTitle>{t("Новый вариант вопроса")}</DialogTitle>
            <DialogDescription>
              {t(
                "Модель готовит один вопрос. Исходный вопрос сохранится до применения варианта."
              )}
            </DialogDescription>
          </DialogHeader>
          <ErrorNotice message={error || job.error} />
          {busy && <PendingIcon />}
          {job.data &&
            ["queued", "running", "failed"].includes(job.data.status) && (
              <JobNotice
                job={job.data}
                retry={() =>
                  void api(`/jobs/${jobId}/retry`, "POST")
                    .then(job.refetch)
                    .catch((e) => setError(errorText(e)))
                }
              />
            )}
          {job.data?.result?.applied_result ? (
            <>
              <p role="status">{t("Вариант применён")}</p>
              <Button
                onClick={() => {
                  onSaved()
                  setOpen(false)
                }}
              >
                {t("Обновить вопрос")}
              </Button>
            </>
          ) : preview && candidate ? (
            <div className="flex flex-col gap-4">
              <div className="rounded-lg border p-3">
                <p className="text-sm text-muted-foreground">
                  {t("Исходный вопрос")}
                </p>
                <p>{card.question}</p>
                <QuestionImageView image={card.images?.question} />
                <ExerciseSolution card={card} />
              </div>
              <div className="rounded-lg border p-3">
                <p className="text-sm text-muted-foreground">{t("Кандидат")}</p>
                <p className="font-medium">{preview.question}</p>
                <ExerciseSolution card={{ ...preview, images: {} }} />
                <ol className="mt-3">
                  {preview.options.map((option, index) => (
                    <li key={index}>
                      {preview.correct_indices.includes(index) ? "✓ " : ""}
                      {option}
                    </li>
                  ))}
                </ol>
                <Sources sources={preview.sources} />
              </div>
              <p className="text-sm text-muted-foreground">
                {t("Правки кандидата сохраняются при применении.")}
              </p>
              <QuestionImages
                card={card}
                value={imageUpdates}
                onChange={setImageUpdates}
                disabled={busy || locked || imageBusy}
                onBusyChange={setImageBusy}
              />
              <EditQuestion
                card={preview}
                showImages={false}
                onSaved={() => {}}
                disabled={busy || locked || imageBusy}
                saveLabel={t("Обновить кандидат")}
                save={async (body) => {
                  const fields = Object.fromEntries(
                    Object.entries(body).filter(([key]) => key !== "version")
                  )
                  const next = { ...candidate, ...fields } as QuestionCandidate
                  if (next.question_type !== "choice")
                    next.answer = exerciseSolution(
                      next.question_type,
                      next.exercise as FullExercise
                    )
                  next.correct_index =
                    next.correct_indices.length === 1
                      ? next.correct_indices[0]
                      : null
                  setEdited({ jobId: jobId!, candidate: next })
                }}
              />
              <Button
                disabled={busy || imageBusy}
                onClick={async () => {
                  setBusy(true)
                  setError(null)
                  setLocked(true)
                  if (!applyRequest.current)
                    applyRequest.current = {
                      candidate,
                      ...(Object.keys(imageUpdates).length
                        ? { image_updates: imageUpdates }
                        : {}),
                    }
                  try {
                    await api(
                      `/jobs/${jobId}/apply-regeneration`,
                      "POST",
                      applyRequest.current
                    )
                    onSaved()
                    setOpen(false)
                  } catch (e) {
                    setError(errorText(e))
                    if (
                      e instanceof APIError &&
                      [409, 422].includes(e.status)
                    ) {
                      setLocked(false)
                      applyRequest.current = null
                    }
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                {t("Применить вариант")}
              </Button>
            </div>
          ) : job.data?.result?.insufficient_reason ? (
            <p role="status">{job.data.result.insufficient_reason}</p>
          ) : null}
          {job.data?.result?.discarded && (
            <p role="status">{t("Вариант отклонён")}</p>
          )}
          {job.data &&
            !job.data.result?.applied_result &&
            !["queued", "running"].includes(job.data.status) && (
              <DialogFooter>
                <Button
                  variant="outline"
                  disabled={busy || locked || imageBusy}
                  onClick={() => void start(true)}
                >
                  {t("Другой вариант")}
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy || imageBusy}
                  onClick={async () => {
                    setBusy(true)
                    setError(null)
                    try {
                      await api(`/jobs/${jobId}/discard-regeneration`, "POST")
                      setOpen(false)
                      setJobId(null)
                      setEdited(null)
                      setLocked(false)
                      applyRequest.current = null
                      request.current = {
                        version: card.version,
                        idempotency_key: crypto.randomUUID(),
                        another_variant: false,
                      }
                    } catch (e) {
                      setError(errorText(e))
                    } finally {
                      setBusy(false)
                    }
                  }}
                >
                  {t("Отклонить вариант")}
                </Button>
              </DialogFooter>
            )}
        </DialogContent>
      </Dialog>
    </>
  )
}
