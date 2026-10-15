import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"
import { t } from "@/i18n"
import {
  questionTypes,
  methodLabel,
  type PracticeMethod,
} from "@/lib/exercises"
import type { Topic, QuestionType, MethodAvailability } from "@/types"
export function readiness(topic: Topic, method: string): MethodAvailability {
  return (
    topic.practice_availability?.[method] || {
      ready_count: ["flashcard", "choice"].includes(method)
        ? topic.card_count
        : 0,
      draft_count: 0,
      needs_options_count: 0,
      preparation_job_id: null,
      preparation_status: null,
      has_ready_materials: topic.document_count > 0,
      last_outcome: null,
    }
  )
}
export function commonTypes(topics: Topic[]) {
  return questionTypes.filter(
    (kind) =>
      topics.length > 0 &&
      topics.every((topic) => readiness(topic, kind).ready_count > 0)
  )
}
export default function PracticeSelector({
  counts,
  method,
  onMethodChange,
  selectedTypes,
  onTypesChange,
  disabled,
}: {
  counts: Topic[]
  method: PracticeMethod
  onMethodChange: (method: PracticeMethod) => void
  selectedTypes: QuestionType[]
  onTypesChange: (types: QuestionType[]) => void
  disabled?: boolean
}) {
  const count = (type: string) =>
    counts.reduce(
      (total, topic) => total + readiness(topic, type).ready_count,
      0
    )
  return (
    <div className="flex flex-col gap-3">
      <Field>
        <FieldLabel htmlFor="practice-method">
          {t("Способ проверки")}
        </FieldLabel>
        <Select
          value={method}
          onValueChange={(value) => onMethodChange(value as PracticeMethod)}
          disabled={disabled}
        >
          <SelectTrigger id="practice-method" className="min-h-11 w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(
              [
                "flashcard",
                ...questionTypes,
                "free_response",
                "mixed",
              ] as PracticeMethod[]
            ).map((type) => (
              <SelectItem key={type} value={type}>
                {methodLabel(type)}
                {type !== "mixed" ? ` · ${count(type)}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {method === "mixed" && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-2 text-sm">{t("Типы вопросов")}</legend>
          {[...questionTypes, "free_response" as const].map((kind) => (
            <label className="flex items-center gap-3" key={kind}>
              <Checkbox
                checked={selectedTypes.includes(kind)}
                disabled={disabled}
                onCheckedChange={(checked) =>
                  onTypesChange(
                    checked
                      ? [...selectedTypes, kind]
                      : selectedTypes.filter((k) => k !== kind)
                  )
                }
              />
              {methodLabel(kind)} · {count(kind)}
            </label>
          ))}
        </fieldset>
      )}
    </div>
  )
}
