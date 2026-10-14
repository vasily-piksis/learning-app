import { Input } from "@/components/ui/input"
import { t } from "@/i18n"
import { Check, X } from "lucide-react"
import type { InputProps } from "./ExerciseInput"
export default function GapExercise({
  card,
  value,
  onChange,
  disabled,
  feedback,
}: InputProps) {
  const exercise = card.exercise
  if (!exercise || !("segments" in exercise)) return null
  const answers = value && "gap_answers" in value ? value.gap_answers : {}
  return (
    <div className="flex flex-wrap items-center gap-2 text-lg leading-loose">
      {exercise.segments.map((segment, index) => {
        if ("text" in segment)
          return (
            <span className="whitespace-pre-wrap" key={index}>
              {segment.text}
            </span>
          )
        const number =
          exercise.gaps.findIndex((g) => g.id === segment.gap_id) + 1
        const part = feedback?.parts?.find((p) => p.id === segment.gap_id)
        return (
          <span key={index} className="inline-flex flex-col gap-1">
            <Input
              className={`w-36 ${part ? (part.correct ? "border-emerald-600 bg-emerald-50" : "border-destructive bg-destructive/10 text-destructive") : ""}`}
              aria-label={t("Пропуск {n}", { n: number })}
              aria-invalid={part ? !part.correct : undefined}
              maxLength={200}
              autoComplete="off"
              spellCheck={false}
              disabled={disabled}
              value={answers[segment.gap_id] || ""}
              onChange={(e) =>
                onChange({
                  gap_answers: { ...answers, [segment.gap_id]: e.target.value },
                })
              }
            />
            {part && (
              <span
                className={`inline-flex items-center gap-1 text-sm ${part.correct ? "text-emerald-800" : "text-destructive"}`}
              >
                {part.correct ? (
                  <Check className="size-4" />
                ) : (
                  <X className="size-4" />
                )}
                {part.correct ? t("Верно!") : t("Неверный ответ")}
              </span>
            )}
          </span>
        )
      })}
    </div>
  )
}
