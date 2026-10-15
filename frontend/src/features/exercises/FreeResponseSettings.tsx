import { useId } from "react"
import { t } from "@/i18n"
import type { PublicFreeResponseExercise, FreeResponseLevel } from "@/types"
import { Input } from "@/components/ui/input"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldDescription,
} from "@/components/ui/field"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  SelectGroup,
} from "@/components/ui/select"

export function validFreeSettings(value: PublicFreeResponseExercise) {
  return (
    /^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$/.test(value.language) &&
    (value.goal === "content" ? value.level === null : value.level !== null) &&
    [value.min_words, value.max_words].every(
      (v) => v === null || (Number.isInteger(v) && v >= 1 && v <= 2000)
    ) &&
    (value.min_words === null ||
      value.max_words === null ||
      value.min_words <= value.max_words)
  )
}
export default function FreeResponseSettings({
  value,
  onChange,
  disabled = false,
}: {
  value: PublicFreeResponseExercise
  onChange: (value: PublicFreeResponseExercise) => void
  disabled?: boolean
}) {
  const id = useId()
  return (
    <FieldGroup>
      <Field>
        <FieldLabel htmlFor={`${id}-language`}>
          {t("Код исходного языка")}
        </FieldLabel>
        <Input
          id={`${id}-language`}
          value={value.language}
          disabled={disabled}
          placeholder="lt, pl, en…"
          onChange={(e) => onChange({ ...value, language: e.target.value })}
        />
        <FieldDescription>
          {t(
            "Подтверди язык материалов. Задание и исправления сохранят этот язык."
          )}
        </FieldDescription>
      </Field>
      {value.goal === "language" && (
        <Field>
          <FieldLabel htmlFor={`${id}-level`}>{t("Уровень CEFR")}</FieldLabel>
          <Select
            value={value.level || ""}
            disabled={disabled}
            onValueChange={(level) =>
              onChange({ ...value, level: level as FreeResponseLevel })
            }
          >
            <SelectTrigger id={`${id}-level`}>
              <SelectValue placeholder={t("Выбери уровень")} />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {["A1", "A2", "B1", "B2", "C1", "C2"].map((level) => (
                  <SelectItem value={level} key={level}>
                    {level}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </Field>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {(["min_words", "max_words"] as const).map((key) => (
          <Field key={key}>
            <FieldLabel htmlFor={`${id}-${key}`}>
              {t(
                key === "min_words"
                  ? "Минимум слов (необязательно)"
                  : "Максимум слов (необязательно)"
              )}
            </FieldLabel>
            <Input
              id={`${id}-${key}`}
              type="number"
              min={1}
              max={2000}
              value={value[key] ?? ""}
              disabled={disabled}
              onChange={(e) =>
                onChange({
                  ...value,
                  [key]: e.target.value === "" ? null : Number(e.target.value),
                })
              }
            />
          </Field>
        ))}
      </div>
      <FieldDescription>
        {t(
          "Диапазон слов — учебная цель. Ответ вне диапазона можно отправить."
        )}
      </FieldDescription>
    </FieldGroup>
  )
}
