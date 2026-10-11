import { t } from "@/i18n"
import { useEffect, useRef, useState } from "react"
import { Layers, ListChecks } from "lucide-react"
import { Button } from "@/components/ui/button"
import {
  ErrorNotice,
  JobNotice,
  Loading,
  PageHeading,
  PendingIcon,
} from "@/components/shared"
import { api, useQuery, errorText, navigate } from "@/api"
import type { Job, Mode, StudySession } from "@/types"

type StartResult = StudySession | { preparation_job: Job }
export default function StartStudy({
  topicIds,
  disabled = false,
}: {
  topicIds: number[]
  disabled?: boolean
}) {
  const [busy, setBusy] = useState<Mode | null>(null)
  const [error, setError] = useState<string | null>(null)
  async function start(mode: Mode) {
    setBusy(mode)
    setError(null)
    try {
      const result = await api<StartResult>("/study", "POST", {
        topic_ids: topicIds,
        mode,
      })
      navigate(
        "preparation_job" in result
          ? `prepare/${result.preparation_job.id}`
          : `study/${result.id}`
      )
    } catch (error) {
      setError(errorText(error))
    } finally {
      setBusy(null)
    }
  }
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <Button
          size="lg"
          disabled={disabled || busy !== null}
          onClick={() => void start("flashcard")}
        >
          {busy === "flashcard" ? (
            <PendingIcon />
          ) : (
            <Layers data-icon="inline-start" />
          )}
          {t("Флеш-карты")}
        </Button>
        <Button
          size="lg"
          variant="outline"
          disabled={disabled || busy !== null}
          onClick={() => void start("quiz")}
        >
          {busy === "quiz" ? (
            <PendingIcon />
          ) : (
            <ListChecks data-icon="inline-start" />
          )}
          {t("Тест")}
        </Button>
      </div>
      <ErrorNotice message={error} />
    </div>
  )
}

export function Preparation({ id }: { id: number }) {
  const job = useQuery<Job>(`/jobs/${id}`, 1000)
  const started = useRef(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (
      job.data?.status !== "succeeded" ||
      started.current ||
      job.data.kind !== "prepare_quiz"
    )
      return
    started.current = true
    api<StartResult>("/study", "POST", {
      topic_ids: job.data.topic_ids,
      mode: "quiz",
    })
      .then((result) =>
        navigate(
          "preparation_job" in result
            ? `prepare/${result.preparation_job.id}`
            : `study/${result.id}`
        )
      )
      .catch((error) => {
        setError(errorText(error))
        started.current = false
      })
  }, [job.data])
  const back =
    job.data?.topic_ids?.length === 1
      ? `#library/topic/${job.data.topic_ids[0]}`
      : "#library"
  return (
    <div className="flex flex-col gap-6">
      <PageHeading
        eyebrow={t("Тест")}
        title={t("Готовим варианты ответа")}
        description={t(
          "Существующие вопросы сохранятся. Варианты готовятся один раз; затем тест запустится."
        )}
      />
      <Button asChild variant="ghost">
        <a href={back}>{t("К теме")}</a>
      </Button>
      <ErrorNotice message={job.error || error} retry={job.refetch} />
      {job.loading ? (
        <Loading />
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
