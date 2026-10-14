import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Check, X } from "lucide-react"
import { t } from "@/i18n"
import type { InputProps } from "./ExerciseInput"
export default function MatchingExercise({
  card,
  value,
  onChange,
  disabled,
  feedback,
}: InputProps) {
  const [selected, setSelected] = useState<string | null>(null)
  const exercise = card.exercise
  if (!exercise || !("left" in exercise)) return null
  const pairs = value && "pairs" in value ? value.pairs : []
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {t("Выбери слово слева, затем соответствие справа.")}
      </p>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-2">
          {exercise.left
            .filter((item) => !pairs.some((p) => p.left_id === item.id))
            .map((item) => (
              <Button
                type="button"
                variant={selected === item.id ? "secondary" : "outline"}
                className="h-auto min-h-11 whitespace-normal"
                key={item.id}
                disabled={disabled}
                aria-pressed={selected === item.id}
                onClick={() =>
                  setSelected(selected === item.id ? null : item.id)
                }
              >
                {item.text}
              </Button>
            ))}
        </div>
        <div className="flex flex-col gap-2">
          {exercise.right
            .filter((item) => !pairs.some((p) => p.right_id === item.id))
            .map((item) => (
              <Button
                type="button"
                variant="outline"
                className="h-auto min-h-11 whitespace-normal"
                key={item.id}
                disabled={disabled || !selected}
                onClick={() => {
                  onChange({
                    pairs: [
                      ...pairs,
                      { left_id: selected!, right_id: item.id },
                    ],
                  })
                  setSelected(null)
                }}
              >
                {item.text}
              </Button>
            ))}
        </div>
      </div>
      {pairs.map((pair) => {
        const left = exercise.left.find((i) => i.id === pair.left_id)?.text,
          right = exercise.right.find((i) => i.id === pair.right_id)?.text
        const part = feedback?.parts?.find((p) => p.id === pair.left_id)
        return (
          <div
            key={pair.left_id}
            className={`flex flex-wrap items-center gap-2 rounded-lg border p-3 ${part ? (part.correct ? "border-emerald-600 bg-emerald-50 text-emerald-900" : "border-destructive bg-destructive/10 text-destructive") : ""}`}
          >
            <span>
              {left} → {right}
            </span>
            {part && (
              <span className="inline-flex items-center gap-1">
                {part.correct ? (
                  <Check className="size-4" />
                ) : (
                  <X className="size-4" />
                )}
                {part.correct ? t("Верно!") : t("Неверный ответ")}
              </span>
            )}
            <Button
              type="button"
              variant="ghost"
              className="ml-auto"
              disabled={disabled}
              aria-label={t("Отменить пару: {left} — {right}", {
                left: left || "",
                right: right || "",
              })}
              onClick={() =>
                onChange({
                  pairs: pairs.filter((p) => p.left_id !== pair.left_id),
                })
              }
            >
              {t("Отменить пару")}
            </Button>
          </div>
        )
      })}
    </div>
  )
}
