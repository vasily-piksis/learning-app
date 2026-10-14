import { Input } from "@/components/ui/input"
import { Field, FieldLabel } from "@/components/ui/field"
import { t } from "@/i18n"
import type { InputProps } from "./ExerciseInput"
export default function TextExercise({
  value,
  onChange,
  disabled,
  feedback,
}: InputProps) {
  return (
    <Field>
      <FieldLabel htmlFor="exercise-answer">{t("Твой ответ")}</FieldLabel>
      <Input
        id="exercise-answer"
        autoComplete="off"
        spellCheck={false}
        maxLength={1000}
        value={value && "text" in value ? value.text : ""}
        aria-invalid={feedback ? !feedback.correct : undefined}
        className={
          feedback && !feedback.correct
            ? "border-destructive bg-destructive/10 text-destructive"
            : undefined
        }
        disabled={disabled}
        onChange={(e) => onChange({ text: e.target.value })}
      />
    </Field>
  )
}
