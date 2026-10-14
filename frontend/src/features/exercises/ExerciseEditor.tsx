import { useId } from "react"
import { t } from "@/i18n"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
  FieldSet,
  FieldLegend,
} from "@/components/ui/field"
import { gapProjection } from "@/lib/exercises"
import type { QuestionType, FullExercise, GapExercise } from "@/types"

export default function ExerciseEditor({
  questionType,
  value,
  onChange,
  disabled = false,
}: {
  questionType: QuestionType
  value: FullExercise
  onChange: (value: FullExercise) => void
  disabled?: boolean
}) {
  const prefix = useId()
  const lines = (text: string) => text.split("\n")
  function updateGap(next: GapExercise) {
    onChange(gapProjection(next))
  }
  return (
    <FieldGroup>
      {questionType === "written" && "accepted_answers" in value && (
        <Field>
          <FieldLabel htmlFor={`${prefix}-answers`}>
            {t("Допустимые ответы")}
          </FieldLabel>
          <Textarea
            id={`${prefix}-answers`}
            value={value.accepted_answers.join("\n")}
            disabled={disabled}
            required
            maxLength={10000}
            onChange={(e) =>
              onChange({ ...value, accepted_answers: lines(e.target.value) })
            }
          />
          <FieldDescription>
            {t("Один допустимый ответ на строку. Язык задания сохраняется.")}
          </FieldDescription>
        </Field>
      )}
      {"case_sensitive" in value && (
        <Field orientation="horizontal">
          <Checkbox
            id={`${prefix}-case`}
            checked={value.case_sensitive}
            disabled={disabled}
            onCheckedChange={(v) =>
              onChange(
                "segments" in value
                  ? gapProjection({ ...value, case_sensitive: v === true })
                  : { ...value, case_sensitive: v === true }
              )
            }
          />
          <FieldLabel htmlFor={`${prefix}-case`}>
            {t("Учитывать регистр")}
          </FieldLabel>
        </Field>
      )}
      {(questionType === "gap" || questionType === "ending") &&
        "segments" in value && (
          <>
            <FieldSet>
              <FieldLegend>{t("Текст с пропусками")}</FieldLegend>
              {value.segments.map((segment, i) => (
                <Field key={i}>
                  {"text" in segment ? (
                    <>
                      <FieldLabel htmlFor={`${prefix}-segment-${i}`}>
                        {t("Текст {n}", { n: i + 1 })}
                      </FieldLabel>
                      <Input
                        id={`${prefix}-segment-${i}`}
                        value={segment.text}
                        disabled={disabled}
                        maxLength={10000}
                        onChange={(e) =>
                          updateGap({
                            ...value,
                            segments: value.segments.map((s, j) =>
                              j === i ? { text: e.target.value } : s
                            ),
                          })
                        }
                      />
                    </>
                  ) : (
                    <FieldDescription>
                      {t(
                        questionType === "ending"
                          ? "Здесь нужно окончание"
                          : "Пропуск {n}",
                        {
                          n:
                            value.gaps.findIndex(
                              (g) => g.id === segment.gap_id
                            ) + 1,
                        }
                      )}
                    </FieldDescription>
                  )}
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={
                      disabled ||
                      ("gap_id" in segment &&
                        (questionType === "ending" || value.gaps.length <= 1))
                    }
                    onClick={() => {
                      const index =
                        "gap_id" in segment
                          ? value.gaps.findIndex(
                              (gap) => gap.id === segment.gap_id
                            )
                          : -1
                      updateGap({
                        ...value,
                        segments: value.segments.filter((_, n) => n !== i),
                        gaps: value.gaps.filter((_, n) => n !== index),
                        accepted_combinations: value.accepted_combinations.map(
                          (row) => row.filter((_, n) => n !== index)
                        ),
                      })
                    }}
                  >
                    {t(
                      "text" in segment
                        ? "Убрать текст {n}"
                        : "Убрать пропуск {n}",
                      {
                        n:
                          "text" in segment
                            ? i + 1
                            : value.gaps.findIndex(
                                (gap) => gap.id === segment.gap_id
                              ) + 1,
                      }
                    )}
                  </Button>
                </Field>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={disabled || value.segments.length >= 30}
                  onClick={() =>
                    updateGap({
                      ...value,
                      segments: [...value.segments, { text: "" }],
                    })
                  }
                >
                  {t("Добавить текст")}
                </Button>
                {questionType === "gap" && (
                  <Button
                    type="button"
                    variant="outline"
                    disabled={
                      disabled ||
                      value.gaps.length >= 6 ||
                      value.segments.length >= 30
                    }
                    onClick={() => {
                      const id = crypto.randomUUID()
                      updateGap({
                        ...value,
                        segments: [...value.segments, { gap_id: id }],
                        gaps: [...value.gaps, { id, accepted_answers: [""] }],
                        accepted_combinations: value.accepted_combinations.map(
                          (row) => [...row, ""]
                        ),
                      })
                    }}
                  >
                    {t("Добавить пропуск")}
                  </Button>
                )}
              </div>
            </FieldSet>
            <FieldSet>
              <FieldLegend>{t("Допустимые сочетания")}</FieldLegend>
              <FieldDescription>
                {t(
                  "Каждая строка — полностью правильное сочетание. Ответы разных строк не смешиваются."
                )}
              </FieldDescription>
              {value.accepted_combinations.map((row, r) => (
                <div className="flex flex-wrap items-end gap-2" key={r}>
                  {value.gaps.map((gap, c) => (
                    <Field className="min-w-24 flex-1" key={gap.id}>
                      <FieldLabel htmlFor={`${prefix}-comb-${r}-${c}`}>
                        {t("Сочетание {n}, пропуск {gap}", {
                          n: r + 1,
                          gap: c + 1,
                        })}
                      </FieldLabel>
                      <Input
                        id={`${prefix}-comb-${r}-${c}`}
                        value={row[c] || ""}
                        disabled={disabled}
                        required
                        maxLength={200}
                        onChange={(e) =>
                          updateGap({
                            ...value,
                            accepted_combinations:
                              value.accepted_combinations.map((values, i) =>
                                i === r
                                  ? values.map((v, j) =>
                                      j === c ? e.target.value : v
                                    )
                                  : values
                              ),
                          })
                        }
                      />
                    </Field>
                  ))}
                  <Button
                    type="button"
                    variant="ghost"
                    disabled={
                      disabled || value.accepted_combinations.length <= 1
                    }
                    onClick={() =>
                      updateGap({
                        ...value,
                        accepted_combinations:
                          value.accepted_combinations.filter((_, i) => i !== r),
                      })
                    }
                  >
                    {t("Убрать сочетание")}
                  </Button>
                </div>
              ))}
              <Button
                type="button"
                variant="outline"
                disabled={disabled || value.accepted_combinations.length >= 20}
                onClick={() =>
                  updateGap({
                    ...value,
                    accepted_combinations: [
                      ...value.accepted_combinations,
                      value.gaps.map(() => ""),
                    ],
                  })
                }
              >
                {t("Добавить сочетание")}
              </Button>
            </FieldSet>
          </>
        )}
      {questionType === "matching" && "pairs" in value && (
        <FieldSet>
          <FieldLegend>{t("Пары")}</FieldLegend>
          {value.pairs.map((pair, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-[1fr_1fr_auto]">
              {(["left", "right"] as const).map((side) => (
                <Field key={side}>
                  <FieldLabel htmlFor={`${prefix}-${side}-${i}`}>
                    {t(side === "left" ? "Слева {n}" : "Справа {n}", {
                      n: i + 1,
                    })}
                  </FieldLabel>
                  <Input
                    id={`${prefix}-${side}-${i}`}
                    value={pair[side]}
                    required
                    maxLength={200}
                    disabled={disabled}
                    onChange={(e) =>
                      onChange({
                        ...value,
                        pairs: value.pairs.map((v, n) =>
                          n === i ? { ...v, [side]: e.target.value } : v
                        ),
                      })
                    }
                  />
                </Field>
              ))}
              <Button
                type="button"
                variant="ghost"
                disabled={disabled || value.pairs.length <= 2}
                onClick={() =>
                  onChange({
                    ...value,
                    pairs: value.pairs.filter((_, n) => n !== i),
                  })
                }
              >
                {t("Убрать пару")}
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            disabled={disabled || value.pairs.length >= 8}
            onClick={() =>
              onChange({
                ...value,
                pairs: [...value.pairs, { left: "", right: "" }],
              })
            }
          >
            {t("Добавить пару")}
          </Button>
        </FieldSet>
      )}
      {questionType === "ordering" && "accepted_orders" in value && (
        <>
          <Field>
            <FieldLabel htmlFor={`${prefix}-tokens`}>
              {t("Слова предложения")}
            </FieldLabel>
            <Textarea
              id={`${prefix}-tokens`}
              value={value.tokens.join("\n")}
              disabled={disabled}
              required
              onChange={(e) =>
                onChange({ ...value, tokens: lines(e.target.value) })
              }
            />
            <FieldDescription>
              {t(
                "Каждое слово на отдельной строке; повторяющиеся слова допустимы."
              )}
            </FieldDescription>
          </Field>
          {value.accepted_orders.map((order, i) => (
            <Field key={i}>
              <FieldLabel htmlFor={`${prefix}-order-${i}`}>
                {t("Допустимый порядок {n}", { n: i + 1 })}
              </FieldLabel>
              <Textarea
                id={`${prefix}-order-${i}`}
                value={order.join("\n")}
                disabled={disabled}
                required
                onChange={(e) =>
                  onChange({
                    ...value,
                    accepted_orders: value.accepted_orders.map((row, n) =>
                      n === i ? lines(e.target.value) : row
                    ),
                  })
                }
              />
            </Field>
          ))}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={disabled || value.accepted_orders.length >= 5}
              onClick={() =>
                onChange({
                  ...value,
                  accepted_orders: [
                    ...value.accepted_orders,
                    [...value.tokens],
                  ],
                })
              }
            >
              {t("Добавить порядок")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={disabled || value.accepted_orders.length <= 1}
              onClick={() =>
                onChange({
                  ...value,
                  accepted_orders: value.accepted_orders.slice(0, -1),
                })
              }
            >
              {t("Убрать порядок")}
            </Button>
          </div>
        </>
      )}
    </FieldGroup>
  )
}
