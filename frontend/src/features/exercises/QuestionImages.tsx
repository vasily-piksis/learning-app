import { useEffect, useId, useState } from "react"
import { api, errorText } from "@/api"
import { t, systemMessage } from "@/i18n"
import type {
  Card,
  ImageCandidate,
  ImageSlot,
  ImageUpdates,
  QuestionImage,
} from "@/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
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
