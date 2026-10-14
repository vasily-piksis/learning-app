import { t } from "@/i18n"
import type { QuestionType, FullExercise, GapExercise } from "@/types"

export const questionTypes: QuestionType[] = [
  "choice",
  "written",
  "gap",
  "ending",
  "matching",
  "ordering",
]
export const questionLabels: Record<QuestionType, string> = {
  choice: "Выбор ответа",
  written: "Письменный ответ",
  gap: "Пропуски",
  ending: "Окончания",
  matching: "Пары",
  ordering: "Сборка предложения",
}
export function questionLabel(type: QuestionType = "choice") {
  return t(questionLabels[type])
}
export function gapProjection(value: GapExercise): GapExercise {
  return {
    ...value,
    gaps: value.gaps.map((gap, index) => {
      const seen = new Set<string>()
      const answers = value.accepted_combinations
        .map((row) => row[index] || "")
        .filter((answer) => {
          const key = answer.normalize("NFC").trim().replace(/\s+/g, " ")
          const normalized = value.case_sensitive ? key : key.toLowerCase()
          if (seen.has(normalized)) return false
          seen.add(normalized)
          return true
        })
      return { ...gap, accepted_answers: answers }
    }),
  }
}
export function exerciseSolution(
  type: QuestionType,
  value: FullExercise | null
): string {
  if (!value) return ""
  if (type === "written" && "accepted_answers" in value)
    return value.accepted_answers.join(" / ")
  if ((type === "gap" || type === "ending") && "segments" in value) {
    return value.accepted_combinations
      .map((row) => {
        const answers = Object.fromEntries(
          value.gaps.map((gap, i) => [gap.id, row[i]])
        )
        return value.segments
          .map((s) => ("text" in s ? s.text : answers[s.gap_id]))
          .join("")
      })
      .join(" / ")
  }
  if (type === "matching" && "pairs" in value)
    return value.pairs.map((p) => `${p.left} → ${p.right}`).join("\n")
  if (type === "ordering" && "accepted_orders" in value)
    return value.accepted_orders.map((row) => row.join(" ")).join(" / ")
  return ""
}

export type PracticeMethod = "flashcard" | QuestionType | "mixed"
export function practiceRequest(
  method: PracticeMethod,
  selectedTypes: QuestionType[]
) {
  return method === "flashcard"
    ? { mode: "flashcard" as const }
    : {
        mode: "quiz" as const,
        question_types: method === "mixed" ? selectedTypes : [method],
      }
}
export function methodLabel(method: string) {
  if (method === "flashcard") return t("Флеш-карты")
  if (method === "mixed") return t("Смешанная практика")
  return questionLabel(method as QuestionType)
}
export function submissionText(
  card: import("@/types").Card,
  value?: import("@/types").Feedback["submission"]
) {
  if (!value) return ""
  if ("text" in value) return value.text
  if ("gap_answers" in value) return Object.values(value.gap_answers).join("; ")
  if ("choices" in value)
    return value.choices.map((i) => card.options[i]).join("; ")
  if ("remembered" in value)
    return value.remembered ? t("Помню") : t("Повторить")
  const exercise = card.exercise
  if ("pairs" in value && exercise && "left" in exercise)
    return value.pairs
      .map(
        (p) =>
          `${exercise.left.find((i) => i.id === p.left_id)?.text} → ${exercise.right.find((i) => i.id === p.right_id)?.text}`
      )
      .join("; ")
  if (
    "order" in value &&
    exercise &&
    "tokens" in exercise &&
    typeof exercise.tokens[0] !== "string"
  )
    return value.order
      .map(
        (id) =>
          (exercise.tokens as { id: string; text: string }[]).find(
            (i) => i.id === id
          )?.text
      )
      .join(" ")
  return ""
}
