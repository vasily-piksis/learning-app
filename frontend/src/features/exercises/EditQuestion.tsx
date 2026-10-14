import { useState } from "react"
import { Pencil } from "lucide-react"
import { t } from "@/i18n"
import { api, errorText } from "@/api"
import type { Card, FullExercise } from "@/types"
import { correctIndices } from "@/lib/answers"
import { exerciseSolution } from "@/lib/exercises"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldSet,
  FieldLegend,
} from "@/components/ui/field"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog"
import { Sources, ErrorNotice, PendingIcon } from "@/components/shared"
import ExerciseEditor from "./ExerciseEditor"

export default function EditQuestion({
  card,
  onSaved,
  save,
  saveLabel,
  disabled = false,
}: {
  card: Card
  onSaved: () => void
  save?: (body: Record<string, unknown>) => Promise<unknown>
  saveLabel?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false),
    [question, setQuestion] = useState(card.question),
    [answer, setAnswer] = useState(card.answer || ""),
    [exercise, setExercise] = useState<FullExercise | null>(
      (card.exercise as FullExercise) || null
    ),
    [options, setOptions] = useState(card.options),
    [correct, setCorrect] = useState<number[]>(correctIndices(card)),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<string | null>(null)
  const specialized = (card.question_type || "choice") !== "choice"
  return (
    <>
      <Button
        variant="ghost"
        disabled={disabled}
        onClick={() => {
          setQuestion(card.question)
          setAnswer(card.answer || "")
          setExercise((card.exercise as FullExercise) || null)
          setOptions(card.options)
          setCorrect(correctIndices(card))
          setError(null)
          setOpen(true)
        }}
        aria-label={t("Изменить карточку")}
      >
        <Pencil data-icon="inline-start" />
        {t("Изменить")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(v) => {
          if (!busy) setOpen(v)
        }}
      >
        <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("Проверим карточку")}</DialogTitle>
            <DialogDescription>
              {t("Можно уточнить вопрос, ответ и варианты перед занятием.")}
            </DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={async (e) => {
              e.preventDefault()
              setBusy(true)
              try {
                const body = {
                  question,
                  ...(specialized
                    ? { exercise }
                    : {
                        answer,
                        options,
                        correct_indices: card.mode === "quiz" ? correct : [],
                      }),
                  version: card.version,
                }
                if (save) await save(body)
                else await api(`/cards/${card.id}`, "PATCH", body)
                setOpen(false)
                onSaved()
              } catch (e) {
                setError(errorText(e))
              } finally {
                setBusy(false)
              }
            }}
          >
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="question">{t("Вопрос")}</FieldLabel>
                <Textarea
                  id="question"
                  value={question}
                  onChange={(e) => setQuestion(e.target.value)}
                  required
                />
              </Field>
              {specialized && exercise ? (
                <>
                  <ExerciseEditor
                    questionType={card.question_type!}
                    value={exercise}
                    onChange={setExercise}
                    disabled={busy}
                  />
                  <Field>
                    <FieldLabel>{t("Полное решение")}</FieldLabel>
                    <p className="whitespace-pre-wrap">
                      {exerciseSolution(card.question_type!, exercise)}
                    </p>
                  </Field>
                </>
              ) : (
                <>
                  <Field>
                    <FieldLabel htmlFor="answer">{t("Ответ")}</FieldLabel>
                    <Textarea
                      id="answer"
                      value={answer}
                      onChange={(e) => setAnswer(e.target.value)}
                      required
                    />
                  </Field>
                </>
              )}
              {!specialized && card.mode === "quiz" && (
                <FieldSet>
                  <FieldLegend>
                    {t("Отметь все правильные варианты")}
                  </FieldLegend>
                  {options.map((option, i) => (
                    <Field key={i}>
                      <FieldLabel htmlFor={`option-${i}`}>
                        {t("Вариант {n}", { n: i + 1 })}
                      </FieldLabel>
                      <div className="flex gap-2">
                        <Input
                          id={`option-${i}`}
                          value={option}
                          onChange={(e) =>
                            setOptions((o) =>
                              o.map((v, n) => (n === i ? e.target.value : v))
                            )
                          }
                          required
                        />
                        <Checkbox
                          checked={correct.includes(i)}
                          aria-label={t("Правильный вариант {n}", { n: i + 1 })}
                          onCheckedChange={(checked) =>
                            setCorrect((indices) =>
                              checked
                                ? [...indices, i].sort((a, b) => a - b)
                                : indices.filter((index) => index !== i)
                            )
                          }
                        />
                      </div>
                    </Field>
                  ))}
                </FieldSet>
              )}
            </FieldGroup>
            <Sources sources={card.sources} />
            <ErrorNotice message={error} />
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
                disabled={busy}
              >
                {t("Отмена")}
              </Button>
              <Button
                disabled={
                  busy ||
                  (!specialized && card.mode === "quiz" && !correct.length)
                }
              >
                {busy && <PendingIcon />}
                {saveLabel || t("Сохранить изменения")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}
