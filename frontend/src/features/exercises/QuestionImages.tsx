import { useCallback, useEffect, useId, useRef, useState } from "react"
import { api, errorText, APIError, useQuery } from "@/api"
import { t, systemMessage, getLocale } from "@/i18n"
import type {
  Card,
  ImageGenerationAvailability,
  ImageGenerationJob,
  ImageCandidate,
  ImageSlot,
  ImageUpdates,
  QuestionImage,
} from "@/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
import { ErrorNotice } from "@/components/shared"

export function QuestionImageView({ image }: { image?: QuestionImage }) {
  if (!image) return null
  return (
    <figure className="flex min-w-0 flex-col gap-2">
      <img
        src={image.url}
        alt={image.alt}
        width={image.width}
        height={image.height}
        className="max-h-80 max-w-full self-start rounded-md object-contain"
      />
      {image.origin === "generated" && (
        <figcaption className="text-sm text-muted-foreground">
          {t("Создано ИИ")}
        </figcaption>
      )}
    </figure>
  )
}

function initialImagePrompt(card: Card, slot: ImageSlot) {
  const text =
    slot === "question" ? card.question : card.answer || card.question
  if (card.language?.toLowerCase().startsWith("pl"))
    return `Ilustracja edukacyjna bez tekstu: ${text}`.slice(0, 2000)
  if (card.language?.toLowerCase().startsWith("ru"))
    return `Учебная иллюстрация без текста: ${text}`.slice(0, 2000)
  if (card.language?.toLowerCase().startsWith("lt"))
    return `Mokomoji iliustracija be teksto: ${text}`.slice(0, 2000)
  if (card.language && !card.language.toLowerCase().startsWith("en"))
    return `Educational illustration without text. Assignment language: ${card.language}; any requested text must be in ${card.language}. ${text}`.slice(
      0,
      2000
    )
  return `Educational illustration without text: ${text}`.slice(0, 2000)
}

function imageJobResponse(value: unknown): ImageGenerationJob {
  const job = value as Partial<ImageGenerationJob> | null
  if (
    !job ||
    typeof job !== "object" ||
    !Number.isSafeInteger(job.id) ||
    (job.id ?? 0) <= 0 ||
    job.kind !== "generate_image" ||
    ![
      "queued",
      "running",
      "succeeded",
      "failed",
      "unknown",
      "cancelled",
    ].includes(job.status || "") ||
    !("result" in job) ||
    (job.result !== null &&
      (typeof job.result !== "object" || Array.isArray(job.result)))
  ) {
    // api() may resolve an error object when a successful HTTP body is unreadable.
    // Keep the counted request frozen until an actual job response settles it.
    throw new APIError("Не удалось прочитать ответ сервера", 0)
  }
  return job as ImageGenerationJob
}

function PaidImageControls({
  card,
  slot,
  initialJob,
  available,
  disabled,
  onCandidate,
  onDiscard,
  refreshAvailability,
}: {
  card: Card
  slot: ImageSlot
  initialJob?: ImageGenerationJob
  available: boolean
  disabled: boolean
  onCandidate: (candidate: ImageCandidate) => void
  onDiscard: (candidate: ImageCandidate) => void
  refreshAvailability: () => void
}) {
  const [prompt, setPrompt] = useState(() => initialImagePrompt(card, slot))
  const [localJob, setLocalJob] = useState<ImageGenerationJob | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const request = useRef<{ path: string; body: unknown } | null>(null)
  const mutation = useRef({ busy: false, revision: 0 })
  const job = localJob || initialJob
  const jobId = job?.id
  const pending = !!job && ["queued", "running"].includes(job.status)
  const id = useId()
  useEffect(() => {
    if (!job?.result?.applied_asset_id && job?.result?.candidate)
      onCandidate(job.result.candidate)
  }, [job, onCandidate])
  useEffect(() => {
    if (!pending || !jobId) return
    let alive = true,
      loading = false
    const timer = window.setInterval(async () => {
      if (loading || mutation.current.busy) return
      const revision = mutation.current.revision
      loading = true
      try {
        const next = imageJobResponse(await api<unknown>(`/jobs/${jobId}`))
        if (alive && revision === mutation.current.revision) {
          setLocalJob(next)
          setError(null)
          if (!["queued", "running"].includes(next.status))
            refreshAvailability()
        }
      } catch (e) {
        if (alive && revision === mutation.current.revision)
          setError(errorText(e))
      } finally {
        loading = false
      }
    }, 1000)
    return () => {
      alive = false
      window.clearInterval(timer)
    }
  }, [jobId, pending, refreshAvailability])
  async function submit(path: string, body?: unknown) {
    if (mutation.current.busy) return
    mutation.current = { busy: true, revision: mutation.current.revision + 1 }
    if (!request.current) request.current = { path, body }
    setBusy(true)
    setError(null)
    try {
      const next = imageJobResponse(
        await api<unknown>(request.current.path, "POST", request.current.body)
      )
      setLocalJob(next)
      request.current = null
      setUncertain(false)
      setAcknowledged(false)
      refreshAvailability()
    } catch (e) {
      setError(errorText(e))
      const networkFailure =
        e instanceof APIError && (e.status === 0 || e.status >= 500)
      setUncertain(networkFailure)
      if (!networkFailure) request.current = null
    } finally {
      mutation.current.busy = false
      setBusy(false)
    }
  }
  const failed = !!job && ["failed", "unknown"].includes(job.status)
  const active =
    !!job &&
    !job.result?.discarded &&
    job.status !== "cancelled" &&
    !job.result?.applied_asset_id
  return (
    <div className="flex min-w-0 flex-col gap-2 rounded-md bg-muted/40 p-3">
      {pending || failed ? (
        <p className="text-sm">
          {t(
            "Эта задача использует исходный запрос и параметры. Для нового запроса сначала откажись от задачи."
          )}
        </p>
      ) : (
        <Field>
          <FieldLabel htmlFor={`${id}-prompt`}>
            {t("Запрос картинки")}
          </FieldLabel>
          <Textarea
            id={`${id}-prompt`}
            value={prompt}
            maxLength={2000}
            disabled={disabled || busy || pending || uncertain}
            onChange={(event) => setPrompt(event.target.value)}
          />
        </Field>
      )}
      <Button
        type="button"
        variant="outline"
        disabled={
          disabled ||
          busy ||
          pending ||
          uncertain ||
          !available ||
          !prompt.trim() ||
          failed
        }
        onClick={() =>
          void submit(`/cards/${card.id}/generate-image`, {
            version: card.version,
            slot,
            prompt,
            idempotency_key: crypto.randomUUID(),
          })
        }
      >
        {t("Сгенерировать картинку (платно)")}
      </Button>
      {pending && (
        <p role="status">{t("Картинка создаётся. Можно вернуться позже.")}</p>
      )}
      {failed && (
        <>
          <p role="status">
            {t(
              job.result?.can_retry_save
                ? "Картинка получена. Повтор сохранения использует готовые данные без новой оплаты."
                : "Результат и списание могут быть неизвестны. Повторная генерация может потребовать дополнительной оплаты."
            )}
          </p>
          {job.result?.can_retry_save ? (
            <Button
              type="button"
              variant="outline"
              disabled={disabled || busy || uncertain}
              onClick={() => void submit(`/jobs/${job.id}/retry-image-save`)}
            >
              {t("Повторить сохранение картинки (бесплатно)")}
            </Button>
          ) : (
            <>
              <label
                className="flex items-start gap-2 text-sm"
                htmlFor={`${id}-cost`}
              >
                <input
                  id={`${id}-cost`}
                  type="checkbox"
                  checked={acknowledged}
                  disabled={disabled || busy || uncertain}
                  onChange={(event) => setAcknowledged(event.target.checked)}
                />
                {t("Я понимаю, что новая попытка может стоить дополнительно")}
              </label>
              <Button
                type="button"
                variant="outline"
                disabled={
                  disabled || busy || uncertain || !available || !acknowledged
                }
                onClick={() =>
                  void submit(`/jobs/${job.id}/retry-image`, {
                    idempotency_key: crypto.randomUUID(),
                    acknowledge_extra_cost: true,
                  })
                }
              >
                {t("Повторить генерацию картинки (платно)")}
              </Button>
            </>
          )}
        </>
      )}
      {uncertain && (
        <>
          <p role="status">
            {t(
              "Ответ сервера не получен. Проверь тот же запрос без новой попытки генерации."
            )}
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={disabled || busy}
            onClick={() =>
              void submit(request.current!.path, request.current!.body)
            }
          >
            {t("Проверить тот же запрос")}
          </Button>
        </>
      )}
      {active && (
        <Button
          type="button"
          variant="ghost"
          disabled={disabled || busy || uncertain}
          onClick={async () => {
            if (mutation.current.busy) return
            mutation.current = {
              busy: true,
              revision: mutation.current.revision + 1,
            }
            setBusy(true)
            setError(null)
            try {
              await api(`/jobs/${job.id}/discard-image`, "POST")
              setLocalJob({
                ...job,
                status: "cancelled",
                result: { discarded: true },
              })
              if (job.result?.candidate) onDiscard(job.result.candidate)
              refreshAvailability()
            } catch (e) {
              setError(errorText(e))
            } finally {
              mutation.current.busy = false
              setBusy(false)
            }
          }}
        >
          {t("Отказаться от генерации картинки")}
        </Button>
      )}
      <ErrorNotice
        message={error || (job?.error ? systemMessage(job.error) : null)}
      />
    </div>
  )
}

export default function QuestionImages({
  card,
  value,
  onChange,
  disabled = false,
  onBusyChange,
}: {
  card: Card
  value: ImageUpdates
  onChange: (updates: ImageUpdates) => void
  disabled?: boolean
  onBusyChange?: (busy: boolean) => void
}) {
  const [drafts, setDrafts] = useState<ImageCandidate[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  const generation = useQuery<ImageGenerationAvailability>("/image-generation")
  const ownJobs = useQuery<ImageGenerationJob[]>(
    `/jobs?card_id=${card.id}&kind=generate_image`
  )
  const refreshRef = useRef(generation.refetch)
  useEffect(() => {
    refreshRef.current = generation.refetch
  }, [generation.refetch])
  const refreshAvailability = useCallback(() => refreshRef.current(), [])
  const mergeCandidate = useCallback((candidate: ImageCandidate) => {
    setDrafts((previous) =>
      previous.some((draft) => draft.id === candidate.id)
        ? previous
        : [candidate, ...previous]
    )
  }, [])
  const available =
    generation.data?.status === "ready" && generation.data.remaining > 0
  let reset = ""
  if (generation.data?.next_reset_at) {
    try {
      reset = new Intl.DateTimeFormat(getLocale(), {
        dateStyle: "medium",
        timeStyle: "short",
        timeZone: generation.data.timezone,
      }).format(new Date(generation.data.next_reset_at))
    } catch {
      /* Invalid operator config must not block uploads. */
    }
  }
  useEffect(() => {
    let alive = true
    api<{ items: ImageCandidate[]; next_cursor: number | null }>(
      `/cards/${card.id}/image-candidates`
    )
      .then((result) => {
        if (alive) {
          setDrafts((previous) => [
            ...(result.items || []),
            ...previous.filter(
              (draft) =>
                !(result.items || []).some((item) => item.id === draft.id)
            ),
          ])
          setCursor(result.next_cursor ?? null)
        }
      })
      .catch((e) => {
        if (alive) setError(errorText(e))
      })
    return () => {
      alive = false
    }
  }, [card.id, card.version])
  async function action(run: () => Promise<void>) {
    setBusy(true)
    onBusyChange?.(true)
    setError(null)
    try {
      await run()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
      onBusyChange?.(false)
    }
  }
  const blocked = busy || disabled
  return (
    <FieldGroup>
      <p className="text-sm text-muted-foreground">
        {t(
          "Картинки — только иллюстрации. Вопрос и правильный ответ должны быть понятны без картинки. Проверь соответствие картинки тексту самостоятельно."
        )}
      </p>
      <p className="text-sm text-muted-foreground">
        {t(
          "Загруженные черновики доступны при возвращении. Текст и подписи сохраняются только при сохранении изменений."
        )}
      </p>
      <p className="text-sm text-muted-foreground">
        {t(
          "Родитель или пользователь проверяет соответствие ИИ-иллюстрации перед сохранением. Это не источник фактов."
        )}
      </p>
      <p className="text-sm text-muted-foreground">
        {t(
          "По умолчанию — без текста. Если нужен текст на картинке, укажи язык задания в запросе."
        )}{" "}
        {card.language || ""}
      </p>
      {generation.data ? (
        <div className="flex flex-col gap-1 text-sm" role="status">
          <p>
            {t(
              "Одна картинка за платную попытку. Стоимость зависит от модели и запроса; точная цена не обещается."
            )}
          </p>
          <p className="break-words">
            {generation.data.model || "—"} · {generation.data.settings?.size} ·{" "}
            {generation.data.settings?.quality} ·{" "}
            {generation.data.settings?.output_format}
          </p>
          <p>
            {t(
              "Общий дневной лимит попыток: {remaining} из {limit}. Это не денежный лимит.",
              {
                remaining: generation.data.remaining,
                limit: generation.data.limit,
              }
            )}
          </p>
          {reset && (
            <p>
              {t("Сброс лимита: {time}", {
                time: `${reset} (${generation.data.timezone})`,
              })}
            </p>
          )}
          {generation.data.status !== "ready" && (
            <p>{t("Генерация картинок недоступна. Загрузка доступна.")}</p>
          )}
          {generation.data.status === "ready" && !generation.data.remaining && (
            <p>{t("Дневной лимит исчерпан.")}</p>
          )}
          <p>
            {t(
              generation.data.access_status === "denied"
                ? "Предыдущая попытка: нет доступа к провайдеру. После обновления доступа можно попробовать явно."
                : generation.data.access_status === "confirmed"
                  ? "Предыдущая попытка подтвердила доступ; будущий запрос может завершиться ошибкой."
                  : "Доступ провайдера проверяется только явным платным запросом."
            )}
          </p>
        </div>
      ) : (
        <p role="status">
          {t("Генерация картинок пока недоступна. Загрузка доступна.")}
        </p>
      )}
      <ErrorNotice
        message={
          generation.error || ownJobs.error
            ? `${t("Генерация картинок")}: ${systemMessage(generation.error || ownJobs.error!)}`
            : null
        }
      />
      {(["question", "answer"] as ImageSlot[]).map((slot) => {
        const current = card.images?.[slot]
        const update = value[slot]
        const selected = update
          ? update.asset_id === current?.asset_id
            ? current
            : drafts.find((d) => d.id === update.asset_id)
          : current
        const displayed = selected
          ? { ...selected, alt: update?.alt ?? selected.alt }
          : undefined
        const label = t(
          slot === "question" ? "Картинка вопроса" : "Картинка ответа"
        )
        return (
          <FieldSet
            key={slot}
            aria-label={label}
            className="min-w-0 rounded-lg border p-3"
          >
            <FieldLegend>{label}</FieldLegend>
            <QuestionImageView image={displayed} />
            <p className="text-sm" role="status">
              {t(
                update?.asset_id === null
                  ? "Картинка будет убрана при сохранении."
                  : update && update.asset_id !== current?.asset_id
                    ? "Картинка будет заменена при сохранении."
                    : "Текущая картинка сохранится."
              )}
            </p>
            <Field>
              <FieldLabel htmlFor={`${id}-${slot}-file`}>
                {t("Загрузить картинку")}
              </FieldLabel>
              <Input
                id={`${id}-${slot}-file`}
                type="file"
                accept="image/jpeg,image/png,image/webp"
                disabled={blocked}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  event.target.value = ""
                  if (!file) return
                  if (file.size > 10 * 1024 * 1024) {
                    setError(t("Картинка должна быть не больше 10 MiB"))
                    return
                  }
                  void action(async () => {
                    const form = new FormData()
                    form.append("file", file)
                    form.append("slot", slot)
                    form.append("version", String(card.version))
                    const draft = await api<ImageCandidate>(
                      `/cards/${card.id}/image-candidates`,
                      "POST",
                      form
                    )
                    setDrafts((previous) => [draft, ...previous])
                    onChange({
                      ...value,
                      [slot]: { asset_id: draft.id, alt: "" },
                    })
                  })
                }}
              />
              <p className="text-sm text-muted-foreground">
                {t("JPEG, PNG или WebP, до 10 MiB и 20 мегапикселей.")}
              </p>
            </Field>
            <PaidImageControls
              card={card}
              slot={slot}
              available={!!available && !ownJobs.loading && !ownJobs.error}
              disabled={blocked}
              initialJob={
                Array.isArray(ownJobs.data)
                  ? ownJobs.data.find(
                      (job) =>
                        job.kind === "generate_image" &&
                        job.card_id === card.id &&
                        job.slot === slot &&
                        !job.result?.discarded &&
                        !job.result?.applied_asset_id &&
                        ["queued", "running", "failed", "unknown"].includes(
                          job.status
                        )
                    )
                  : undefined
              }
              onCandidate={mergeCandidate}
              onDiscard={(candidate) => {
                setDrafts((previous) =>
                  previous.filter((draft) => draft.id !== candidate.id)
                )
                setCursor((previous) => (previous === null ? null : 0))
                if (value[slot]?.asset_id === candidate.id) {
                  const next = { ...value }
                  delete next[slot]
                  onChange(next)
                }
              }}
              refreshAvailability={refreshAvailability}
            />
            {selected && (
              <Field>
                <FieldLabel htmlFor={`${id}-${slot}-alt`}>
                  {t("Подпись картинки")}
                </FieldLabel>
                <Input
                  id={`${id}-${slot}-alt`}
                  value={displayed?.alt || ""}
                  maxLength={500}
                  disabled={blocked}
                  onChange={(event) =>
                    onChange({
                      ...value,
                      [slot]: {
                        asset_id: selected.asset_id,
                        alt: event.target.value,
                      },
                    })
                  }
                />
              </Field>
            )}
            <div className="flex flex-wrap gap-2">
              {update && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={blocked}
                  onClick={() => {
                    const next = { ...value }
                    delete next[slot]
                    onChange(next)
                  }}
                >
                  {t("Оставить текущую картинку")}
                </Button>
              )}
              {selected && (
                <Button
                  type="button"
                  variant="outline"
                  disabled={blocked}
                  onClick={() =>
                    onChange({ ...value, [slot]: { asset_id: null, alt: "" } })
                  }
                >
                  {t("Убрать картинку")}
                </Button>
              )}
            </div>
            {drafts
              .filter((d) => d.slot === slot)
              .map((draft) => (
                <div
                  key={draft.id}
                  className="flex flex-col gap-2 rounded-md border p-2"
                >
                  <a
                    className="text-sm underline"
                    href={draft.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {t("Кандидат")} · {draft.width} × {draft.height}
                  </a>
                  {!draft.can_apply && (
                    <p className="text-sm">
                      {t(
                        "Вопрос изменён; проверь картинку перед новой привязкой."
                      )}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={blocked || !draft.can_apply}
                      onClick={() =>
                        onChange({
                          ...value,
                          [slot]: { asset_id: draft.id, alt: "" },
                        })
                      }
                    >
                      {t("Использовать черновик")}
                    </Button>
                    {!draft.can_apply && (
                      <Button
                        type="button"
                        variant="outline"
                        disabled={blocked}
                        onClick={() =>
                          void action(async () => {
                            const rebased = await api<ImageCandidate>(
                              `/image-candidates/${draft.id}/rebase`,
                              "POST",
                              { version: card.version }
                            )
                            setDrafts((previous) =>
                              previous.map((d) =>
                                d.id === draft.id ? rebased : d
                              )
                            )
                          })
                        }
                      >
                        {t("Привязать к текущей версии (бесплатно)")}
                      </Button>
                    )}
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={blocked}
                      onClick={() =>
                        void action(async () => {
                          await api(`/image-candidates/${draft.id}`, "DELETE")
                          setDrafts((previous) =>
                            previous.filter((d) => d.id !== draft.id)
                          )
                          // Deletion shifts server offsets; merge the next page from the start.
                          setCursor((previous) =>
                            previous === null ? null : 0
                          )
                          if (update?.asset_id === draft.id) {
                            const next = { ...value }
                            delete next[slot]
                            onChange(next)
                          }
                        })
                      }
                    >
                      {t("Удалить черновик")}
                    </Button>
                  </div>
                </div>
              ))}
          </FieldSet>
        )
      })}
      {cursor !== null && (
        <Button
          type="button"
          variant="outline"
          disabled={blocked}
          onClick={() =>
            void action(async () => {
              const result = await api<{
                items: ImageCandidate[]
                next_cursor: number | null
              }>(`/cards/${card.id}/image-candidates?cursor=${cursor}`)
              setDrafts((previous) => [
                ...previous,
                ...result.items.filter(
                  (item) => !previous.some((draft) => draft.id === item.id)
                ),
              ])
              setCursor(result.next_cursor)
            })
          }
        >
          {t("Показать ещё черновики")}
        </Button>
      )}
      <ErrorNotice
        message={
          error ? `${t("Черновики картинок")}: ${systemMessage(error)}` : null
        }
      />
    </FieldGroup>
  )
}
