import { correctIndices } from "@/lib/answers"
import { cn } from "@/lib/utils"
import { Checkbox } from "@/components/ui/checkbox"
import { FieldSet, FieldLegend } from "@/components/ui/field"
import { t } from "@/i18n"
import { useRef, useState } from "react"
import {
  ArrowLeft,
  ArrowRight,
  Eye,
  Check,
  RotateCcw,
  Sparkles,
  Send,
  Trophy,
  X,
} from "lucide-react"
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
import { Textarea } from "@/components/ui/textarea"
import { Field, FieldLabel } from "@/components/ui/field"
import {
  PageHeading,
  ErrorNotice,
  Loading,
  Sources,
  PendingIcon,
  JobNotice,
} from "@/components/shared"
import { api, useQuery, errorText, APIError, navigate } from "@/api"
import type {
  StudySession,
  Feedback,
  Card as StudyCard,
  Explanation,
  Job,
} from "@/types"

export default function Study({ id }: { id: number }) {
  const session = useQuery<StudySession>(
    Number.isSafeInteger(id) && id > 0 ? `/study/${id}` : null
  )
  if (!Number.isSafeInteger(id) || id <= 0)
    return <ErrorNotice message={t("Занятие не найдено")} />
  if (session.loading) return <Loading />
  if (session.error)
    return <ErrorNotice message={session.error} retry={session.refetch} />
  if (!session.data) return null
  const value = session.data
  const activeTopics = value.active_topic_ids ?? value.topic_ids
  const topicId =
    value.topic_ids?.length === 1 && activeTopics?.includes(value.topic_ids[0])
      ? value.topic_ids[0]
      : null
  const back = {
    href: topicId ? `#library/topic/${topicId}` : "#library",
    label: topicId ? t("К теме") : t("Вернуться в библиотеку"),
  }
  return (
    <div className="study-page">
      <Button asChild variant="ghost" className="self-start">
        <a href={back.href}>
          <ArrowLeft data-icon="inline-start" />
          {back.label}
        </a>
      </Button>
      <PageHeading
        eyebrow={t("Немного практики каждый день")}
        title={value.topic_names.join(" · ")}
        description={
          value.mode === "quiz"
            ? t("Не спеши. Выбери ответ, который кажется верным.")
            : t("Попробуй вспомнить ответ, прежде чем открыть карточку.")
        }
      />
      {value.card ? (
        <Question
          key={value.position}
          session={value}
          onNext={session.refetch}
        />
      ) : (
        <div className="flex flex-col gap-8">
          <Completed session={value} back={back} />
          {value.review?.length ? (
            <section className="flex flex-col gap-4">
              <h2>{t("Ответы и объяснения")}</h2>
              {value.review.map((item) => (
                <ReviewCard
                  key={item.position}
                  sessionId={value.id}
                  item={item}
                />
              ))}
            </section>
          ) : null}
        </div>
      )}
    </div>
  )
}
function Question({
  session,
  onNext,
}: {
  session: StudySession
  onNext: () => void
}) {
  const [card, setCard] = useState<StudyCard>(session.card!),
    [choice, setChoice] = useState<number | null>(null),
    [choices, setChoices] = useState<number[]>([]),
    [feedback, setFeedback] = useState<Feedback | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [answerLocked, setAnswerLocked] = useState(false)
  const answerRequest = useRef<{
    position: number
    idempotency_key: string
    choice?: number
    choices?: number[]
    remembered?: boolean
  } | null>(null)
  async function answer(remembered?: boolean) {
    setAnswerLocked(true)
    if (!answerRequest.current)
      answerRequest.current = {
        position: session.position,
        idempotency_key: crypto.randomUUID(),
        ...(session.mode === "quiz"
          ? card.multiple_answers
            ? { choices }
            : { choice: choice! }
          : { remembered }),
      }
    setBusy(true)
    setError(null)
    try {
      setFeedback(
        await api<Feedback>(
          `/study/${session.id}/answer`,
          "POST",
          answerRequest.current
        )
      )
    } catch (e) {
      setError(errorText(e))
      if (e instanceof APIError && e.status === 409) {
        answerRequest.current = null
        onNext()
      }
    } finally {
      setBusy(false)
    }
  }
  const shown = feedback?.card || card,
    revealed = !!feedback || !!card.revealed
  return (
    <div className="flex flex-col gap-6">
      <div className="study-progress">
        <div className="flex items-center justify-between gap-3">
          <span>
            {t("Карточка {position} из {count}", {
              position: session.position + 1,
              count: session.count,
            })}
          </span>
          <Badge variant="secondary">
            {session.mode === "quiz" ? t("Тест") : t("Флеш-карта")}
          </Badge>
        </div>
        <Progress
          value={
            ((session.answered + (feedback ? 1 : 0)) / session.count) * 100
          }
          aria-label={t("Прогресс занятия")}
        />
      </div>
      <Card className="question-card">
        <CardHeader>
          <p className="eyebrow">{t("Вспоминаем и понимаем")}</p>
          <CardTitle className="question-title">{shown.question}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {session.mode === "quiz" && (
            <FieldSet className="quiz-options">
              {shown.multiple_answers && (
                <FieldLegend>{t("Выбери все правильные ответы")}</FieldLegend>
              )}
              {shown.options.map((option, i) => {
                const correct = !!feedback && correctIndices(shown).includes(i)
                const selected = shown.multiple_answers
                  ? choices.includes(i)
                  : choice === i
                const incorrect = !!feedback && selected && !correct
                if (shown.multiple_answers)
                  return (
                    <label
                      key={i}
                      className={cn(
                        "quiz-option flex items-center gap-3 rounded-xl border p-4",
                        selected && "bg-secondary",
                        feedback &&
                          correct &&
                          "correct border-emerald-600 bg-emerald-50 text-emerald-900",
                        incorrect &&
                          "incorrect border-destructive bg-destructive/10 text-destructive"
                      )}
                    >
                      <Checkbox
                        checked={selected}
                        disabled={busy || !!feedback || answerLocked}
                        aria-label={option}
                        onCheckedChange={(checked) =>
                          setChoices((indices) =>
                            checked
                              ? [...indices, i].sort((a, b) => a - b)
                              : indices.filter((index) => index !== i)
                          )
                        }
                      />
                      <span>{option}</span>
                      {correct && <Check aria-hidden="true" />}
                      {incorrect && <X aria-hidden="true" />}
                      {feedback && correct && !selected && (
                        <span className="text-sm">
                          {t("Пропущен правильный ответ")}
                        </span>
                      )}
                    </label>
                  )
                return (
                  <Button
                    key={i}
                    variant={choice === i ? "secondary" : "outline"}
                    className={[
                      "quiz-option h-auto justify-start text-left whitespace-normal",
                      feedback && "disabled:opacity-100",
                      correct &&
                        "correct border-emerald-600 bg-emerald-50 text-emerald-900",
                      incorrect &&
                        "incorrect border-destructive bg-destructive/10 text-destructive",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    disabled={busy || !!feedback || answerLocked}
                    aria-pressed={choice === i}
                    onClick={() => setChoice(i)}
                  >
                    <span className="option-letter">
                      {String.fromCharCode(65 + i)}
                    </span>
                    <span>{option}</span>
                    {correct && (
                      <>
                        <Check data-icon="inline-end" />
                        <span className="sr-only">{t("Правильный ответ")}</span>
                      </>
                    )}
                    {incorrect && (
                      <>
                        <X data-icon="inline-end" />
                        <span className="sr-only">{t("Неверный ответ")}</span>
                      </>
                    )}
                  </Button>
                )
              })}
            </FieldSet>
          )}
          {revealed && (
            <div className="answer-content">
              <p
                className={`eyebrow ${feedback ? (feedback.correct ? "text-emerald-800" : "text-destructive") : ""}`}
                role={feedback ? "status" : undefined}
              >
                {feedback
                  ? feedback.correct
                    ? t("Верно!")
                    : t("Неверно. Правильный ответ:")
                  : t("Ответ")}
              </p>
              <p className="answer-text">{shown.answer}</p>
              <Sources sources={shown.sources} />
            </div>
          )}
          <ErrorNotice message={error} />
        </CardContent>
        <CardFooter className="flex flex-wrap gap-3">
          {feedback ? (
            <Button className="ml-auto" onClick={onNext}>
              {session.position + 1 < session.count
                ? t("Следующая карточка")
                : t("Результат занятия")}
              <ArrowRight data-icon="inline-end" />
            </Button>
          ) : session.mode === "quiz" ? (
            <Button
              className="ml-auto"
              disabled={
                busy ||
                (card.multiple_answers ? !choices.length : choice === null)
              }
              onClick={() => void answer()}
            >
              {busy && <PendingIcon />}
              {t("Проверить ответ")}
            </Button>
          ) : !card.revealed ? (
            <Button
              className="mx-auto"
              disabled={busy}
              onClick={async () => {
                setBusy(true)
                try {
                  const result = await api<StudySession>(
                    `/study/${session.id}/reveal`,
                    "POST",
                    { position: session.position }
                  )
                  setCard(result.card!)
                } catch (e) {
                  setError(errorText(e))
                  if (e instanceof APIError && e.status === 409) onNext()
                } finally {
                  setBusy(false)
                }
              }}
            >
              {busy ? <PendingIcon /> : <Eye data-icon="inline-start" />}
              {t("Показать ответ")}
            </Button>
          ) : answerLocked ? (
            <Button disabled={busy} onClick={() => void answer()}>
              {busy && <PendingIcon />}
              {t("Повторить сохранение ответа")}
            </Button>
          ) : (
            <div className="grade-buttons">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void answer(false)}
              >
                <RotateCcw data-icon="inline-start" />
                {t("Повторить")}
              </Button>
              <Button disabled={busy} onClick={() => void answer(true)}>
                <Check data-icon="inline-start" />
                {t("Помню")}
              </Button>
            </div>
          )}
        </CardFooter>
      </Card>
      <ExplanationPanel
        sessionId={session.id}
        position={session.position}
        enabled={revealed}
      />
      <p className="study-note">
        {t(
          "Ответы сохраняются после проверки. Можно продолжить позже с любого устройства."
        )}
      </p>
    </div>
  )
}
function Completed({
  session,
  back,
}: {
  session: StudySession
  back: { href: string; label: string }
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  return (
    <Card className="completion-card">
      <CardHeader>
        <div className="completion-icon">
          <Trophy />
        </div>
        <CardTitle className="text-3xl">{t("Ещё один шаг вперёд")}</CardTitle>
        <CardDescription>
          {t("Занятие завершено. Результат уже в твоей истории.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="score">
          <strong>
            {session.correct}
            <span> / {session.count}</span>
          </strong>
          <p>
            {session.mode === "quiz"
              ? t("верных ответов")
              : t("карточек, которые помнишь")}
          </p>
        </div>
        <ErrorNotice message={error} />
        {session.correct < session.count && (
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              try {
                const repeated = await api<StudySession>(
                  `/study/${session.id}/repeat`,
                  "POST"
                )
                navigate(`study/${repeated.id}`)
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {busy ? <PendingIcon /> : <RotateCcw data-icon="inline-start" />}
            {t("Повторить сложные карточки")}
          </Button>
        )}
        <Button asChild variant="outline">
          <a href={back.href}>{back.label}</a>
        </Button>
      </CardContent>
    </Card>
  )
}
function ReviewCard({
  sessionId,
  item,
}: {
  sessionId: number
  item: {
    position: number
    card: StudyCard
    correct: boolean
    choice: number | null
    choices?: number[]
  }
}) {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <CardHeader>
        <Badge
          variant={item.correct ? "secondary" : "outline"}
          className="self-start"
        >
          {item.correct ? t("Помнишь") : t("Для повторения")}
        </Badge>
        <CardTitle>{item.card.question}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {(item.choices?.length || item.choice != null) && (
          <p className="text-sm text-muted-foreground">
            {t("Твой ответ: {answer}", {
              answer: (item.choices || [item.choice!])
                .map((index) => item.card.options[index])
                .join("; "),
            })}
          </p>
        )}
        <p className="whitespace-pre-wrap">{item.card.answer}</p>
        <Sources sources={item.card.sources} />
        <Button
          variant="outline"
          className="self-start"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? t("Скрыть обсуждение") : t("Объяснения и вопросы")}
        </Button>
        {open && (
          <ExplanationPanel
            sessionId={sessionId}
            position={item.position}
            enabled
          />
        )}
      </CardContent>
    </Card>
  )
}
function ExplanationPanel({
  sessionId,
  position,
  enabled,
}: {
  sessionId: number
  position: number
  enabled: boolean
}) {
  const explanations = useQuery<Explanation[]>(
    `/study/${sessionId}/explanations?position=${position}`,
    2500
  )
  const jobs = useQuery<Job[]>(
    `/study/${sessionId}/explanation-jobs?position=${position}`,
    2500
  )
  const [question, setQuestion] = useState(""),
    [jobId, setJobId] = useState<number | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const currentJobId =
    jobId || jobs.data?.find((j) => j.status !== "succeeded")?.id || null
  const active = useQuery<Job>(
    currentJobId ? `/jobs/${currentJobId}` : null,
    currentJobId ? 2500 : 0
  )
  const processing =
    busy ||
    active.data?.status === "queued" ||
    active.data?.status === "running"
  async function explain(text: string) {
    setBusy(true)
    setError(null)
    try {
      const previous = explanations.data?.at(-1)
      const job = await api<Job>(`/study/${sessionId}/explain`, "POST", {
        position,
        question: text,
        parent_id: previous?.id || null,
      })
      setJobId(job.id)
      setQuestion("")
      jobs.refetch()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Card className="explanation-card">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-5 text-primary" />
          {t("Разберёмся вместе")}
        </CardTitle>
        <CardDescription>
          {enabled
            ? t(
                "Попроси объяснить ответ простыми словами. Можно задать уточняющий вопрос."
              )
            : t("Объяснение станет доступно после открытия ответа.")}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        <ErrorNotice message={error || explanations.error || active.error} />
        {explanations.data?.map((value) => (
          <div className="explanation-message" key={value.id}>
            <p className="explanation-question">{value.question}</p>
            <p className="leading-relaxed whitespace-pre-wrap">{value.text}</p>
            {value.example && <p className="analogy">{value.example}</p>}
            <Sources sources={value.sources} />
          </div>
        ))}
        {active.data &&
          (active.data.status === "queued" ||
            active.data.status === "running" ||
            active.data.status === "failed") && (
            <JobNotice
              job={active.data}
              retry={async () => {
                try {
                  await api(`/jobs/${currentJobId}/retry`, "POST")
                  active.refetch()
                } catch (e) {
                  setError(errorText(e))
                }
              }}
            />
          )}
        {!explanations.data?.length ? (
          <Button
            variant="outline"
            className="self-start"
            disabled={!enabled || processing}
            onClick={() =>
              void explain(t("Объясни проще, как ребёнку пяти лет"))
            }
          >
            {processing ? (
              <PendingIcon />
            ) : (
              <Sparkles data-icon="inline-start" />
            )}
            {t("Объясни проще")}
          </Button>
        ) : (
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault()
              void explain(question.trim())
            }}
          >
            <Field>
              <FieldLabel htmlFor="followup">
                {t("Твой уточняющий вопрос")}
              </FieldLabel>
              <Textarea
                id="followup"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                disabled={processing}
                placeholder={t("Например: почему это произошло?")}
              />
            </Field>
            <Button
              className="self-end"
              disabled={processing || !question.trim() || !enabled}
            >
              {processing ? <PendingIcon /> : <Send data-icon="inline-start" />}
              {t("Спросить")}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  )
}
