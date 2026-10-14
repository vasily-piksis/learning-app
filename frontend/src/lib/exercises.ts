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
