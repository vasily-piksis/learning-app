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
    return <ErrorNotice message="Занятие не найдено" />
  if (session.loading) return <Loading />
  if (session.error)
    return <ErrorNotice message={session.error} retry={session.refetch} />
  if (!session.data) return null
  const value = session.data
  return (
    <div className="study-page">
      <Button asChild variant="ghost" className="self-start">
        <a href="#history">
          <ArrowLeft data-icon="inline-start" />
          Мои занятия
        </a>
      </Button>
      <PageHeading
        eyebrow="Немного практики каждый день"
        title={value.topic_names.join(" · ")}
        description={
          value.mode === "quiz"
            ? "Не спеши. Выбери ответ, который кажется верным."
            : "Попробуй вспомнить ответ, прежде чем открыть карточку."
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
          <Completed session={value} />
          {value.review?.length ? (
            <section className="flex flex-col gap-4">
              <h2>Ответы и объяснения</h2>
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
    [feedback, setFeedback] = useState<Feedback | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const [answerLocked, setAnswerLocked] = useState(false)
  const answerRequest = useRef<{
    position: number
    idempotency_key: string
    choice?: number
    remembered?: boolean
  } | null>(null)
  async function answer(remembered?: boolean) {
    setAnswerLocked(true)
    if (!answerRequest.current)
      answerRequest.current = {
        position: session.position,
        idempotency_key: crypto.randomUUID(),
        ...(session.mode === "quiz" ? { choice: choice! } : { remembered }),
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
            Карточка {session.position + 1} из {session.count}
          </span>
          <Badge variant="secondary">
            {session.mode === "quiz" ? "Тест" : "Флеш-карта"}
          </Badge>
        </div>
        <Progress
          value={
            ((session.answered + (feedback ? 1 : 0)) / session.count) * 100
          }
          aria-label="Прогресс занятия"
        />
      </div>
      <Card className="question-card">
        <CardHeader>
          <p className="eyebrow">Вспоминаем и понимаем</p>
          <CardTitle className="question-title">{shown.question}</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-5">
          {session.mode === "quiz" && (
            <div className="quiz-options">
              {shown.options.map((option, i) => (
                <Button
                  key={i}
                  variant={choice === i ? "secondary" : "outline"}
                  className={
                    feedback && shown.correct_index === i
                      ? "quiz-option correct h-auto justify-start text-left whitespace-normal"
                      : "quiz-option h-auto justify-start text-left whitespace-normal"
                  }
                  disabled={busy || !!feedback || answerLocked}
                  aria-pressed={choice === i}
                  onClick={() => setChoice(i)}
                >
                  <span className="option-letter">
                    {String.fromCharCode(65 + i)}
                  </span>
                  <span>{option}</span>
                  {feedback && shown.correct_index === i && (
                    <Check data-icon="inline-end" />
                  )}
                </Button>
              ))}
            </div>
          )}
          {revealed && (
            <div className="answer-content">
              <p className="eyebrow">
                {feedback
                  ? feedback.correct
                    ? "Верно!"
                    : "Давай запомним"
                  : "Ответ"}
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
                ? "Следующая карточка"
                : "Результат занятия"}
              <ArrowRight data-icon="inline-end" />
            </Button>
          ) : session.mode === "quiz" ? (
            <Button
              className="ml-auto"
              disabled={busy || choice === null}
              onClick={() => void answer()}
            >
              {busy && <PendingIcon />}Проверить ответ
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
              Показать ответ
            </Button>
          ) : answerLocked ? (
            <Button disabled={busy} onClick={() => void answer()}>
              {busy && <PendingIcon />}Повторить сохранение ответа
            </Button>
          ) : (
            <div className="grade-buttons">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => void answer(false)}
              >
                <RotateCcw data-icon="inline-start" />
                Повторить
              </Button>
              <Button disabled={busy} onClick={() => void answer(true)}>
                <Check data-icon="inline-start" />
                Помню
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
        Ответы сохраняются после проверки. Можно продолжить позже с любого
        устройства.
      </p>
    </div>
  )
}
function Completed({ session }: { session: StudySession }) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  return (
    <Card className="completion-card">
      <CardHeader>
        <div className="completion-icon">
          <Trophy />
        </div>
        <CardTitle className="text-3xl">Ещё один шаг вперёд</CardTitle>
        <CardDescription>
          Занятие завершено. Результат уже в твоей истории.
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
              ? "верных ответов"
              : "карточек, которые помнишь"}
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
            Повторить сложные карточки
          </Button>
        )}
        <Button asChild variant="outline">
          <a href="#library">Вернуться в библиотеку</a>
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
          {item.correct ? "Помнишь" : "Для повторения"}
        </Badge>
        <CardTitle>{item.card.question}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {item.choice !== null && (
          <p className="text-sm text-muted-foreground">
            Твой ответ: {item.card.options[item.choice]}
          </p>
        )}
        <p className="whitespace-pre-wrap">{item.card.answer}</p>
        <Sources sources={item.card.sources} />
        <Button
          variant="outline"
          className="self-start"
          onClick={() => setOpen((v) => !v)}
        >
          {open ? "Скрыть обсуждение" : "Объяснения и вопросы"}
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
          Разберёмся вместе
        </CardTitle>
        <CardDescription>
          {enabled
            ? "Попроси объяснить ответ простыми словами. Можно задать уточняющий вопрос."
            : "Объяснение станет доступно после открытия ответа."}
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
            onClick={() => void explain("Объясни проще, как ребёнку пяти лет")}
          >
            {processing ? (
              <PendingIcon />
            ) : (
              <Sparkles data-icon="inline-start" />
            )}
            Объясни проще
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
              <FieldLabel htmlFor="followup">Твой уточняющий вопрос</FieldLabel>
              <Textarea
                id="followup"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                maxLength={2000}
                disabled={processing}
                placeholder="Например: почему это произошло?"
              />
            </Field>
            <Button
              className="self-end"
              disabled={processing || !question.trim() || !enabled}
            >
              {processing ? <PendingIcon /> : <Send data-icon="inline-start" />}
              Спросить
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  )
}
