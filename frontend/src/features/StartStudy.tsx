import { t } from "@/i18n"
import { useRef, useState } from "react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import {
  ErrorNotice,
  JobNotice,
  Loading,
  PageHeading,
  PendingIcon,
} from "@/components/shared"
import { api, useQuery, errorText, navigate } from "@/api"
import {
  methodLabel,
  practiceRequest,
  type PracticeMethod,
} from "@/lib/exercises"
import PracticeSelector, {
  commonTypes,
  readiness,
} from "./exercises/PracticeSelector"
import type {
  Job,
  QuestionType,
  StudySession,
  Topic,
  Card as StudyCard,
} from "@/types"

export default function StartStudy({
  topicIds,
  topics,
  disabled = false,
}: {
  topicIds: number[]
  topics?: Topic[]
  disabled?: boolean
}) {
  const counts =
    topics ||
    topicIds.map((id) => ({
      id,
      name: `#${id}`,
      subject_id: 0,
      version: 1,
      card_count: disabled ? 0 : 1,
      document_count: 0,
    }))
  const [method, setMethod] = useState<PracticeMethod>("flashcard"),
    [types, setTypes] = useState<QuestionType[]>(() => commonTypes(counts)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null),
    [preparing, setPreparing] = useState(false)
  const requestKey = useRef(crypto.randomUUID())
  const [paidOptIn, setPaidOptIn] = useState(false)
  const requested = method === "mixed" ? types : [method]
  const rows = counts.flatMap((topic) =>
    requested.map((kind) => ({ topic, kind, ...readiness(topic, kind) }))
  )
  const paid = requested.some((kind) =>
    ["free_response", "picture_description"].includes(kind)
  )
  const unavailable =
    paid &&
    rows.some(
      (row) =>
        ["free_response", "picture_description"].includes(row.kind) &&
        row.runtime_unavailable
    )
  const missing = rows.filter((row) => !row.ready_count)
  const actionable = missing[0]
  const ready =
    counts.length > 0 && requested.length > 0 && missing.length === 0
  const pending = missing.find((row) => row.preparation_job_id)
  const drafts = missing.find((row) => row.draft_count > 0)
  async function openJob(id: number) {
    const job = await api<Job>(`/jobs/${id}`)
    navigate(job.kind === "prepare_quiz" ? `prepare/${id}` : `generation/${id}`)
  }
  async function start() {
    setError(null)
    setBusy(true)
    try {
      if (ready) {
        const session = await api<StudySession>("/study", "POST", {
          topic_ids: topicIds,
          ...practiceRequest(method, types),
          ...(paid ? { include_ai_evaluated: paidOptIn } : {}),
        })
        navigate(`study/${session.id}`)
      } else if (
        pending?.preparation_job_id &&
        pending.kind === "picture_description"
      )
        navigate(`library/topic/${pending.topic.id}/create/picture_description`)
      else if (pending?.preparation_job_id)
        await openJob(pending.preparation_job_id)
      else if (drafts)
        navigate(
          `library/topic/${drafts.topic.id}/${drafts.kind === "picture_description" ? "create/picture_description" : "questions"}`
        )
      else if (actionable) {
        if (actionable.kind === "choice" && actionable.needs_options_count > 0)
          setPreparing(true)
        else
          navigate(
            `library/topic/${actionable.topic.id}/${actionable.kind === "picture_description" || actionable.has_ready_materials ? `create/${actionable.kind}` : "materials"}`
          )
      }
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  const label =
    !counts.length || ready
      ? t("Начать занятие")
      : pending
        ? ["queued", "running"].includes(pending.preparation_status || "")
          ? t("Открыть подготовку")
          : t("Проверить задания")
        : drafts
          ? t("Проверить задания")
          : t("Подготовить задания")
  return (
    <div className="flex flex-col gap-4">
      <PracticeSelector
        counts={counts}
        method={method}
        selectedTypes={types}
        onTypesChange={setTypes}
        onMethodChange={(next) => {
          setMethod(next)
          if (next === "mixed") setTypes(commonTypes(counts))
          setPreparing(false)
          setError(null)
        }}
        disabled={busy}
      />
      {rows.map((row) => (
        <div className="text-sm" key={`${row.topic.id}/${row.kind}`}>
          <p>
            {row.topic.name} · {methodLabel(row.kind)}:{" "}
            {t("Готово {ready}; проверить {drafts}", {
              ready: row.ready_count,
              drafts: row.draft_count,
            })}
          </p>
          {row.last_outcome && (
            <p className="text-muted-foreground">
              {row.last_outcome.reason}
              {row.last_outcome.stale &&
                ` ${t("Материалы изменились; можно попробовать снова.")}`}
            </p>
          )}
          {row.preparation_job_id && row.ready_count > 0 && (
            <Button
              variant="link"
              disabled={busy}
              onClick={() =>
                void openJob(row.preparation_job_id!).catch((e) =>
                  setError(errorText(e))
                )
              }
            >
              {t("Открыть дополнительную подготовку")}
            </Button>
          )}
        </div>
      ))}
      {paid && (
        <>
          <label className="flex items-start gap-3">
            <Checkbox
              checked={paidOptIn}
              onCheckedChange={(v) => setPaidOptIn(v === true)}
            />
            {t("Включить платную проверку ИИ")}
          </label>
          {unavailable && (
            <p>
              {t(
                "Проверка ИИ сейчас недоступна. Сохранённые задания доступны."
              )}
            </p>
          )}
        </>
      )}
      {missing.length > 0 && (
        <p>
          {t("Подготовка нужна: {items}", {
            items: missing
              .map((row) => `${row.topic.name} — ${methodLabel(row.kind)}`)
              .join("; "),
          })}
        </p>
      )}
      <Button
        size="lg"
        disabled={
          (ready && paid && (!paidOptIn || unavailable)) ||
          busy ||
          !topicIds.length ||
          !requested.length
        }
        onClick={() => void start()}
      >
        {busy && <PendingIcon />}
        {label}
      </Button>
      {preparing && actionable && (
        <div className="rounded-xl border p-4">
          <p>
            {t(
              "Варианты ответа создаются моделью. Проверь их перед сохранением; занятие не начнётся автоматически."
            )}
          </p>
          <Button
            className="mt-3"
            disabled={busy}
            onClick={async () => {
              setBusy(true)
              setError(null)
              try {
                const job = await api<Job>("/study/prepare-options", "POST", {
                  topic_ids: [actionable.topic.id],
                  idempotency_key: requestKey.current,
                })
                navigate(`prepare/${job.id}`)
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {t("Создать варианты ответа")}
          </Button>
        </div>
      )}
      <ErrorNotice message={error} />
    </div>
  )
}

export function Preparation({ id }: { id: number }) {
  const job = useQuery<Job>(`/jobs/${id}`, 1000)
  const cards = useQuery<StudyCard[]>(
    job.data?.status === "succeeded" ? "/cards" : null
  )
  const [selected, setSelected] = useState<number[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const key = useRef(crypto.randomUUID())
  const back =
    job.data?.topic_ids?.length === 1
      ? `#library/topic/${job.data.topic_ids[0]}`
      : "#library"
  const candidates =
    job.data?.result?.candidates?.filter(
      (c) => !job.data?.result?.applied_card_ids?.includes(c.card_id)
    ) || []
  async function mutate(path: string, body?: unknown) {
    setBusy(true)
    setError(null)
    try {
      await api(path, "POST", body)
      job.refetch()
      cards.refetch()
      setSelected([])
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="flex flex-col gap-6">
      <PageHeading
        eyebrow={t("Выбор ответа")}
        title={t("Готовим варианты ответа")}
        description={t(
          "Проверь варианты и сохрани выбранные. Затем вернись в тему и начни занятие."
        )}
      />
      <Button asChild variant="ghost">
        <a href={back}>{t("К теме")}</a>
      </Button>
      <ErrorNotice
        message={job.error || cards.error || error}
        retry={job.refetch}
      />
      {job.loading ? (
        <Loading />
      ) : (
        job.data && (
          <JobNotice
            job={job.data}
            retry={() => void mutate(`/jobs/${id}/retry`)}
          />
        )
      )}
      {job.data?.status === "failed" && (
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              const next = await api<Job>("/study/prepare-options", "POST", {
                topic_ids: job.data?.topic_ids,
                idempotency_key: key.current,
              })
              navigate(`prepare/${next.id}`)
            } catch (e) {
              setError(errorText(e))
            } finally {
              setBusy(false)
            }
          }}
        >
          {t("Подготовить заново")}
        </Button>
      )}
      {job.data?.result?.discarded ? (
        <p role="status">{t("Подготовка отклонена")}</p>
      ) : (
        candidates.map((candidate) => {
          const original = cards.data?.find((c) => c.id === candidate.card_id)
          return (
            <Card key={candidate.card_id}>
              <CardHeader>
                <CardTitle>
                  {original?.question || `#${candidate.card_id}`}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-3">
                <label className="flex items-center gap-3">
                  <Checkbox
                    checked={selected.includes(candidate.card_id)}
                    disabled={
                      busy ||
                      !original ||
                      original.version !== candidate.version
                    }
                    onCheckedChange={(checked) =>
                      setSelected((ids) =>
                        checked
                          ? [...ids, candidate.card_id]
                          : ids.filter((id) => id !== candidate.card_id)
                      )
                    }
                  />
                  {t("Выбрать: {question}", {
                    question: original?.question || `#${candidate.card_id}`,
                  })}
                </label>
                <ol>
                  {candidate.options.map((option, i) => (
                    <li key={i}>
                      {candidate.correct_indices.includes(i) ? "✓ " : ""}
                      <span>{option}</span>
                    </li>
                  ))}
                </ol>
              </CardContent>
            </Card>
          )
        })
      )}
      {candidates.length > 0 && !job.data?.result?.discarded && (
        <div className="flex flex-wrap gap-3">
          <Button
            disabled={busy || !selected.length}
            onClick={() =>
              void mutate(`/jobs/${id}/save-preparation`, {
                card_ids: selected,
              })
            }
          >
            {t("Сохранить выбранные ({count})", { count: selected.length })}
          </Button>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => void mutate(`/jobs/${id}/discard-preparation`)}
          >
            {t("Отклонить подготовку")}
          </Button>
        </div>
      )}
    </div>
  )
}
