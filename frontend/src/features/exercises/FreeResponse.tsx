import { useEffect, useRef, useState } from "react"
import { CircleAlert } from "lucide-react"
import { api } from "@/api"
import { t } from "@/i18n"
import { countWords } from "@/lib/word-count"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { PendingIcon, Sources } from "@/components/shared"
import { QuestionImageView } from "./QuestionImages"
import ExerciseSolution from "./ExerciseSolution"
import EvaluationFeedback from "./EvaluationFeedback"
import type {
  StudySession,
  Feedback,
  EvaluationGrade,
  EvaluationState,
} from "@/types"

type Frozen = {
  path: string
  body: {
    position?: number
    free_text?: string
    idempotency_key: string
    acknowledge_extra_cost?: true
  }
  text: string
}
const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value)
const integer = (value: unknown) => Number.isSafeInteger(value)
// These fields reach Sources and ExerciseSolution after a paid response is accepted.
// Reject malformed render data before clearing the persisted request key.
function renderableSources(value: unknown) {
  return (
    Array.isArray(value) &&
    value.every(
      (source) =>
        object(source) &&
        integer(source.document_id) &&
        integer(source.page) &&
        (source.available === undefined ||
          typeof source.available === "boolean") &&
        (source.name === undefined || typeof source.name === "string") &&
        (source.url === undefined || typeof source.url === "string") &&
        (source.start_seconds === undefined ||
          (typeof source.start_seconds === "number" &&
            Number.isFinite(source.start_seconds)))
    )
  )
}
function renderableImages(value: unknown) {
  if (value === undefined) return true
  return (
    object(value) &&
    [value.question, value.answer].every(
      (image) =>
        image === undefined ||
        (object(image) &&
          typeof image.asset_id === "string" &&
          typeof image.url === "string" &&
          typeof image.alt === "string" &&
          typeof image.mime === "string" &&
          integer(image.width) &&
          Number(image.width) > 0 &&
          integer(image.height) &&
          Number(image.height) > 0 &&
          (image.origin === "upload" || image.origin === "generated"))
    )
  )
}
export function isEvaluationFeedback(
  value: unknown
): value is Feedback & EvaluationGrade {
  if (!object(value) || !object(value.card) || !object(value.word_limit))
    return false
  return (
    integer(value.evaluation_id) &&
    Number(value.evaluation_id) > 0 &&
    ["free_response", "picture_description"].includes(
      String(value.card.question_type)
    ) &&
    object(value.card.exercise) &&
    typeof value.card.exercise.model_answer === "string" &&
    Array.isArray(value.card.exercise.rubric) &&
    value.card.exercise.rubric.every(
      (r) =>
        object(r) &&
        typeof r.id === "string" &&
        typeof r.label === "string" &&
        integer(r.weight)
    ) &&
    Array.isArray(value.card.exercise.expected_points) &&
    value.card.exercise.expected_points.every(
      (p) =>
        object(p) &&
        typeof p.id === "string" &&
        typeof p.text === "string" &&
        typeof p.essential === "boolean"
    ) &&
    integer(value.session_id) &&
    integer(value.position) &&
    integer(value.next_position) &&
    integer(value.card.id) &&
    typeof value.card.question === "string" &&
    (value.card.answer === undefined ||
      typeof value.card.answer === "string") &&
    renderableSources(value.card.sources) &&
    renderableImages(value.card.images) &&
    integer(value.score) &&
    Number(value.score) >= 0 &&
    Number(value.score) <= 100 &&
    typeof value.correct === "boolean" &&
    integer(value.word_count) &&
    Number(value.word_count) >= 1 &&
    Number(value.word_count) <= 2000 &&
    value.word_count_version === 1 &&
    [value.word_limit.min, value.word_limit.max].every(
      (v) => v === null || (integer(v) && Number(v) >= 1 && Number(v) <= 2000)
    ) &&
    typeof value.word_limit.met === "boolean" &&
    typeof value.language_match === "boolean" &&
    typeof value.summary === "string" &&
    Array.isArray(value.rubric_scores) &&
    value.rubric_scores.every(
      (r) =>
        object(r) &&
        typeof r.criterion_id === "string" &&
        integer(r.score) &&
        Number(r.score) >= 0 &&
        Number(r.score) <= 4 &&
        typeof r.explanation === "string"
    ) &&
    Array.isArray(value.point_checks) &&
    value.point_checks.every(
      (p) =>
        object(p) &&
        typeof p.point_id === "string" &&
        typeof p.met === "boolean" &&
        Array.isArray(p.evidence) &&
        p.evidence.every(
          (e) =>
            object(e) &&
            ((e.kind === "text" &&
              object(e.source) &&
              integer(e.source.document_id) &&
              integer(e.source.page) &&
              typeof e.quote === "string") ||
              (e.kind === "image" &&
                typeof e.asset_id === "string" &&
                /^[a-f0-9]{32}$/.test(e.asset_id) &&
                typeof e.sha256 === "string" &&
                /^[a-f0-9]{64}$/.test(e.sha256)))
        )
    ) &&
    Array.isArray(value.corrections) &&
    value.corrections.every(
      (c) =>
        object(c) &&
        [c.original, c.suggested, c.explanation].every(
          (s) => typeof s === "string"
        )
    ) &&
    Array.isArray(value.suggestions) &&
    value.suggestions.every((s) => typeof s === "string")
  )
}
function isState(value: unknown, full: boolean): value is EvaluationState {
  return (
    object(value) &&
    integer(value.evaluation_id) &&
    Number(value.evaluation_id) > 0 &&
    integer(value.job_id) &&
    Number(value.job_id) > 0 &&
    typeof value.status === "string" &&
    ["queued", "running", "failed", "unknown", "completed"].includes(
      value.status
    ) &&
    (!full ||
      (object(value.submission) &&
        typeof value.submission.free_text === "string" &&
        value.submission.audio_answer_id === null)) &&
    (value.status !== "completed" || isEvaluationFeedback(value.feedback))
  )
}
export default function FreeResponse({
  session,
  onNext,
}: {
  session: StudySession
  onNext: () => void
}) {
  const card = session.card!
  const settings =
    card.exercise && "goal" in card.exercise ? card.exercise : null
  const storageKey = `free-response-v1:${session.id}:${session.position}`
  const [frozen, setFrozen] = useState<Frozen | null>(() => {
    try {
      const saved: unknown = JSON.parse(
        sessionStorage.getItem(storageKey) || "null"
      )
      return object(saved) &&
        typeof saved.text === "string" &&
        object(saved.body) &&
        typeof saved.body.idempotency_key === "string" &&
        (saved.path === `/study/${session.id}/answer` ||
          /^\/evaluations\/\d+\/retry$/.test(String(saved.path)))
        ? (saved as Frozen)
        : null
    } catch {
      return null
    }
  })
  const [text, setText] = useState(frozen?.text || "")
  const [state, setState] = useState<EvaluationState | null>(null)
  const [feedback, setFeedback] = useState<(Feedback & EvaluationGrade) | null>(
    null
  )
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [ack, setAck] = useState(false)
  const sending = useRef(false)
  function remember(value: Frozen) {
    // Persist before sending; failure leaves the request unsent and preserves its key in memory.
    setFrozen(value)
    sessionStorage.setItem(storageKey, JSON.stringify(value))
  }
  function acceptFeedback(value: unknown) {
    if (
      !isEvaluationFeedback(value) ||
      value.session_id !== session.id ||
      value.position !== session.position ||
      value.next_position !== session.position + 1 ||
      value.card.id !== card.id
    )
      return false
    setFeedback(value)
    setUncertain(false)
    setFrozen(null)
    sessionStorage.removeItem(storageKey)
    return true
  }
  useEffect(() => {
    let alive = true,
      pending = false
    async function load() {
      if (pending) return
      pending = true
      try {
        const value = await api<unknown>(
          `/study/${session.id}/evaluations?position=${session.position}`
        )
        if (!alive) return
        if (value === null) {
          setLoaded(true)
          return
        }
        if (!isState(value, true)) throw new Error("Invalid evaluation status")
        if (value.status === "completed") {
          if (
            !isEvaluationFeedback(value.feedback) ||
            value.feedback.session_id !== session.id ||
            value.feedback.position !== session.position ||
            value.feedback.next_position !== session.position + 1 ||
            value.feedback.card.id !== card.id
          )
            throw new Error("Invalid feedback")
          setFeedback(value.feedback)
          setFrozen(null)
          sessionStorage.removeItem(storageKey)
        }
        setState(value)
        setText(value.submission!.free_text)
        setLoaded(true)
        setUncertain(false)
      } catch {
        if (alive) setUncertain(true)
      } finally {
        pending = false
      }
    }
    void load()
    const timer = window.setInterval(() => void load(), 1500)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [session.id, session.position, storageKey, card.id])
  async function send(retry = false) {
    if (sending.current) return
    sending.current = true
    setBusy(true)
    setUncertain(false)
    try {
      const request =
        frozen ||
        (retry && state
          ? {
              path: `/evaluations/${state.evaluation_id}/retry`,
              text,
              body: {
                idempotency_key: crypto.randomUUID(),
                acknowledge_extra_cost: true as const,
              },
            }
          : {
              path: `/study/${session.id}/answer`,
              text,
              body: {
                position: session.position,
                free_text: text,
                idempotency_key: crypto.randomUUID(),
              },
            })
      remember(request)
      const value = await api<unknown>(request.path, "POST", request.body)
      if (acceptFeedback(value)) return
      if (!isState(value, false) || value.status === "completed")
        throw new Error("Invalid acknowledgement")
      setState({
        ...value,
        submission: { free_text: request.text, audio_answer_id: null },
      })
      setAck(false)
      // A valid acknowledgement settles this HTTP operation; the immutable answer remains frozen by state.
      setFrozen(null)
      sessionStorage.removeItem(storageKey)
    } catch {
      setUncertain(true)
    } finally {
      sending.current = false
      setBusy(false)
    }
  }
  const words = countWords(text),
    chars = Array.from(text).length
  const outside =
    !!settings &&
    ((settings.min_words !== null && words < settings.min_words) ||
      (settings.max_words !== null && words > settings.max_words))
  const failed = state?.status === "failed" || state?.status === "unknown"
  const pending = state?.status === "queued" || state?.status === "running"
  const locked = !loaded || busy || !!frozen || !!state || !!feedback
  return (
    <Card className="question-card">
      <CardHeader>
        <CardTitle>{card.question}</CardTitle>
        <p>
          {settings?.language} {settings?.level}
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <QuestionImageView image={card.images?.question} />
        <Field>
          <FieldLabel htmlFor="free-response">
            {t("Твой развёрнутый ответ")}
          </FieldLabel>
          <Textarea
            id="free-response"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={locked}
            className="min-h-48"
            aria-describedby="free-count"
          />
        </Field>
        <p id="free-count">
          {settings &&
          (settings.min_words !== null || settings.max_words !== null)
            ? t("Слов: {count} · цель {min}–{max}", {
                count: words,
                min: settings.min_words ?? "—",
                max: settings.max_words ?? "—",
              })
            : t("Слов: {count}", { count: words })}
        </p>
        {outside && !feedback && (
          <p className="flex items-start gap-2">
            <CircleAlert aria-hidden="true" />
            {t(
              "Вне рекомендуемого диапазона слов. Ответ всё равно можно отправить."
            )}
          </p>
        )}
        {(chars > 10000 || words > 2000) && (
          <p role="alert">{t("Максимум 10000 символов и 2000 слов.")}</p>
        )}
        {uncertain && (
          <p role="status">
            {t(
              "Не удалось подтвердить состояние. Ответ сохранён; проверь отправку снова."
            )}
          </p>
        )}
        {pending && !feedback && (
          <p role="status" className="flex gap-2">
            <PendingIcon />
            {t("Проверяем ответ")}
          </p>
        )}
        {failed && !feedback && (
          <p role="status">
            {t(
              state.error_code === "quota_exceeded"
                ? "Дневной лимит проверок исчерпан"
                : state.error_code === "runtime_unavailable"
                  ? "Проверка ИИ сейчас недоступна. Сохранённые задания доступны."
                  : state.status === "unknown"
                    ? "Результат неизвестен; запрос мог быть оплачен. Автоматического повтора нет"
                    : "Проверка не завершена. Оценка не выставлена."
            )}
          </p>
        )}
        {feedback ? (
          <>
            <EvaluationFeedback feedback={feedback} card={feedback.card} />
            <ExerciseSolution card={feedback.card} />
            <Sources sources={feedback.card.sources} />
            <Button onClick={onNext}>
              {t(
                session.position + 1 < session.count
                  ? "Следующая карточка"
                  : "Результат занятия"
              )}
            </Button>
          </>
        ) : frozen ? (
          <Button disabled={busy} onClick={() => void send()}>
            {t("Проверить отправку снова")}
          </Button>
        ) : failed ? (
          <>
            <Field orientation="horizontal">
              <Checkbox
                id="retry-cost"
                checked={ack}
                disabled={busy}
                onCheckedChange={(v) => setAck(v === true)}
              />
              <FieldLabel htmlFor="retry-cost">
                {t("Понимаю, что новый запрос может стоить дополнительно")}
              </FieldLabel>
            </Field>
            <Button disabled={!ack || busy} onClick={() => void send(true)}>
              {t("Повторить тот же ответ (платно)")}
            </Button>
          </>
        ) : (
          !state && (
            <Button
              disabled={
                !loaded || busy || !words || words > 2000 || chars > 10000
              }
              onClick={() => void send()}
            >
              {t("Оценить с ИИ (платно)")}
            </Button>
          )
        )}
      </CardContent>
    </Card>
  )
}
