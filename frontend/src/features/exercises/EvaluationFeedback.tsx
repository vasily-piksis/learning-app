import { Check, CircleAlert, Pencil } from "lucide-react"
import { t } from "@/i18n"
import type { Card, EvaluationGrade } from "@/types"
export default function EvaluationFeedback({
  feedback,
  card,
}: {
  feedback: EvaluationGrade
  card: Card
}) {
  const exercise =
    card.exercise && "rubric" in card.exercise ? card.exercise : null
  return (
    <section className="flex flex-col gap-4" aria-label={t("Оценка ответа")}>
      <p
        role="status"
        className={`flex items-center gap-2 font-semibold ${feedback.correct ? "text-emerald-800" : "text-destructive"}`}
      >
        {feedback.correct ? (
          <Check aria-hidden="true" />
        ) : (
          <CircleAlert aria-hidden="true" />
        )}
        {t(
          feedback.correct ? "Задание выполнено" : "Задание пока не выполнено"
        )}
      </p>
      <p role="status">{t("Оценка: {score}/100", { score: feedback.score })}</p>
      <p className="whitespace-pre-wrap">{feedback.summary}</p>
      <ul className="flex flex-col gap-2">
        {feedback.rubric_scores.map((row) => (
          <li key={row.criterion_id}>
            <strong>
              {exercise?.rubric.find((r) => r.id === row.criterion_id)?.label ||
                row.criterion_id}
              : {row.score}/4
            </strong>
            <p>{row.explanation}</p>
          </li>
        ))}
      </ul>
      <ul className="flex flex-col gap-2">
        {feedback.point_checks.map((row) => (
          <li className="flex items-start gap-2" key={row.point_id}>
            {row.met ? (
              <Check aria-hidden="true" />
            ) : (
              <CircleAlert aria-hidden="true" />
            )}
            <span>
              {t(row.met ? "Учтено" : "Нужно дополнить")}:{" "}
              {exercise?.expected_points.find((p) => p.id === row.point_id)
                ?.text || row.point_id}
            </span>
          </li>
        ))}
      </ul>
      <p className="flex items-center gap-2">
        {feedback.word_limit.met ? (
          <Check aria-hidden="true" />
        ) : (
          <CircleAlert aria-hidden="true" />
        )}
        {t(
          feedback.word_limit.met
            ? "Диапазон слов соблюдён"
            : "Диапазон слов не соблюдён"
        )}
      </p>
      <p>
        {t("Слов: {count}", { count: feedback.word_count })} ·{" "}
        {feedback.word_limit.min ?? "—"}–{feedback.word_limit.max ?? "—"}
      </p>
      <p>
        {t(
          feedback.language_match
            ? "Язык задания сохранён"
            : "Язык ответа отличается от задания"
        )}
      </p>
      {feedback.corrections.map((correction, i) => (
        <div key={i} className="flex flex-col gap-1">
          <p className="flex items-start gap-2">
            <Pencil aria-hidden="true" />
            {t("Исправление")}: {correction.original} → {correction.suggested}
          </p>
          <p>{correction.explanation}</p>
        </div>
      ))}
      {feedback.suggestions.length > 0 && (
        <ul>
          {feedback.suggestions.map((suggestion, i) => (
            <li key={i}>{suggestion}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
