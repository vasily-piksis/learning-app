import { useRef, useState } from "react"
import { api, errorText, useQuery } from "@/api"
import { t } from "@/i18n"
import type { Card as StudyCard, PublicFreeResponseExercise } from "@/types"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "@/components/ui/card"
import { Field, FieldLabel } from "@/components/ui/field"
import { ErrorNotice, EditCard } from "@/components/shared"
import FreeResponseSettings, { validFreeSettings } from "./FreeResponseSettings"
import RegenerateQuestion from "./RegenerateQuestion"
import { QuestionImageView } from "./QuestionImages"

export default function PictureDrafts({ topicId }: { topicId: number }) {
  const [settings, setSettings] = useState<PublicFreeResponseExercise>({
    goal: "language",
    language: "",
    level: null,
    min_words: null,
    max_words: null,
  })
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const key = useRef(crypto.randomUUID())
  const cards = useQuery<StudyCard[]>(`/cards?topic_id=${topicId}`, 1500)
  return (
    <div className="flex flex-col gap-5">
      <Card>
        <CardHeader>
          <CardTitle>{t("Описание картинки")}</CardTitle>
          <CardDescription>
            {t(
              "Подготовка и проверка описания используют платную модель с изображением."
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <ErrorNotice message={error || cards.error} />
          <Field>
            <FieldLabel htmlFor="picture-upload">
              {t("Исходная картинка")}
            </FieldLabel>
            <Input
              id="picture-upload"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              disabled={busy}
              onChange={(e) => {
                setFile(e.target.files?.[0] || null)
                key.current = crypto.randomUUID()
              }}
            />
          </Field>
          <FreeResponseSettings
            picture
            value={settings}
            disabled={busy}
            onChange={(value) => {
              setSettings(value)
              key.current = crypto.randomUUID()
            }}
          />
        </CardContent>
        <CardFooter>
          <Button
            disabled={
              busy ||
              !file ||
              !validFreeSettings(settings) ||
              !["pl", "en", "ru", "lt"].includes(settings.language)
            }
            onClick={async () => {
              if (!file) return
              setBusy(true)
              setError(null)
              try {
                const data = new FormData()
                data.append("image", file)
                data.append("key", key.current)
                for (const field of [
                  "language",
                  "level",
                  "min_words",
                  "max_words",
                ] as const)
                  if (settings[field] !== null)
                    data.append(field, String(settings[field]))
                await api(`/topics/${topicId}/picture-drafts`, "POST", data)
                cards.refetch()
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            {t("Создать черновик без ИИ")}
          </Button>
        </CardFooter>
      </Card>
      {cards.data
        ?.filter((card) => card.question_type === "picture_description")
        .map((card) => (
          <Card key={card.id}>
            <CardHeader>
              <CardTitle>{card.question}</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <QuestionImageView image={card.images?.question} />
              {card.answer ? (
                <p>{card.answer}</p>
              ) : (
                <p>{t("Сначала подготовь и примени критерии по картинке.")}</p>
              )}
            </CardContent>
            <CardFooter className="flex-wrap gap-2">
              <EditCard card={card} onSaved={cards.refetch} />
              <RegenerateQuestion card={card} onSaved={cards.refetch} />
              <Button
                disabled={
                  busy ||
                  !card.exercise ||
                  !("model_answer" in card.exercise) ||
                  card.status === "saved"
                }
                onClick={async () => {
                  setBusy(true)
                  setError(null)
                  try {
                    await api("/cards/save", "POST", { card_ids: [card.id] })
                    cards.refetch()
                  } catch (e) {
                    setError(errorText(e))
                  } finally {
                    setBusy(false)
                  }
                }}
              >
                {t("Сохранить")}
              </Button>
            </CardFooter>
          </Card>
        ))}
      <Button asChild variant="outline">
        <a href={`#library/topic/${topicId}`}>{t("К теме")}</a>
      </Button>
    </div>
  )
}
