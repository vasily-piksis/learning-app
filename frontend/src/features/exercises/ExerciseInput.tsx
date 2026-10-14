import type { Card, ExerciseSubmission, Feedback } from "@/types"
import TextExercise from "./TextExercise"
import GapExercise from "./GapExercise"
import MatchingExercise from "./MatchingExercise"
import OrderingExercise from "./OrderingExercise"
import { t } from "@/i18n"
export type InputProps = {
  card: Card
  value: ExerciseSubmission | null
  onChange: (value: ExerciseSubmission) => void
  disabled: boolean
  feedback?: Feedback | null
}
export function completeAnswer(card: Card, value: ExerciseSubmission | null) {
  if (!value) return false
  const exercise = card.exercise
  switch (card.question_type) {
    case "written":
      return "text" in value && !!value.text.trim()
    case "gap":
    case "ending":
      return (
        !!exercise &&
        "gaps" in exercise &&
        "gap_answers" in value &&
        exercise.gaps.every(
          (g) =>
            Object.hasOwn(value.gap_answers, g.id) &&
            typeof value.gap_answers[g.id] === "string" &&
            !!value.gap_answers[g.id].trim()
        )
      )
    case "matching":
      return (
        !!exercise &&
        "left" in exercise &&
        "pairs" in value &&
        value.pairs.length === exercise.left.length
      )
    case "ordering":
      return (
        !!exercise &&
        "tokens" in exercise &&
        "order" in value &&
        value.order.length === exercise.tokens.length
      )
    default:
      return false
  }
}
export default function ExerciseInput(props: InputProps) {
  const renderers = {
    written: TextExercise,
    gap: GapExercise,
    ending: GapExercise,
    matching: MatchingExercise,
    ordering: OrderingExercise,
  }
  const kind = props.card.question_type
  const Component = kind && kind !== "choice" ? renderers[kind] : null
  return (
    <div className="flex flex-col gap-4">
      {Component && <Component {...props} />}
      {!!props.feedback?.parts?.length && (
        <p role="status">
          {t("Верных частей: {correct} из {count}", {
            correct: props.feedback.parts.filter((p) => p.correct).length,
            count: props.feedback.parts.length,
          })}
        </p>
      )}
      {props.feedback?.message_code === "incompatible_combination" && (
        <p className="text-destructive" role="status">
          {t(
            "Эти ответы допустимы по отдельности, но не сочетаются друг с другом."
          )}
        </p>
      )}
    </div>
  )
}
