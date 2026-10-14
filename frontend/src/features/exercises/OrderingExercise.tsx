import { Button } from "@/components/ui/button"
import { t } from "@/i18n"
import type { InputProps } from "./ExerciseInput"
export default function OrderingExercise({
  card,
  value,
  onChange,
  disabled,
}: InputProps) {
  const exercise = card.exercise
  if (
    !exercise ||
    !("tokens" in exercise) ||
    typeof exercise.tokens[0] === "string"
  )
    return null
  const tokens = exercise.tokens as { id: string; text: string }[]
  const order = value && "order" in value ? value.order : []
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {t(
          "Нажимай слова в нужном порядке. Нажми собранное слово, чтобы вернуть его."
        )}
      </p>
      <div
        className="flex min-h-16 flex-wrap items-center gap-2 rounded-xl border p-3"
        aria-label={t("Твоё предложение")}
      >
        {order.map((id, index) => (
          <Button
            type="button"
            key={id}
            variant="secondary"
            disabled={disabled}
            aria-label={t("Вернуть слово {n}: {word}", {
              n: index + 1,
              word: tokens.find((t) => t.id === id)?.text || "",
            })}
            onClick={() => onChange({ order: order.filter((i) => i !== id) })}
          >
            {tokens.find((t) => t.id === id)?.text}
          </Button>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        {tokens
          .filter((token) => !order.includes(token.id))
          .map((token) => (
            <Button
              type="button"
              key={token.id}
              variant="outline"
              disabled={disabled}
              onClick={() => onChange({ order: [...order, token.id] })}
            >
              {token.text}
            </Button>
          ))}
      </div>
      <Button
        type="button"
        variant="ghost"
        className="self-start"
        disabled={disabled || !order.length}
        onClick={() => onChange({ order: [] })}
      >
        {t("Очистить предложение")}
      </Button>
    </div>
  )
}
