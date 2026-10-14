import { t } from "@/i18n"
import { useState } from "react"
import { Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Dialog,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog"
import StartStudy from "./StartStudy"
import type { Topic, Subject } from "@/types"
export default function StudySelection({
  topics,
  subjects,
}: {
  topics: Topic[]
  subjects: Subject[]
}) {
  const [selected, setSelected] = useState<number[]>([])
  const available = topics
  const chosen = selected.filter((id) =>
    available.some((topic) => topic.id === id)
  )
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" disabled={!available.length}>
          <Play data-icon="inline-start" />
          {t("Выбрать темы для повторения")}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("Что повторим?")}</DialogTitle>
          <DialogDescription>
            {t(
              "Выбери темы и способ проверки. Для каждой темы видны готовые задания и недостающая подготовка."
            )}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          {available.map((topic) => (
            <label
              key={topic.id}
              className="flex cursor-pointer items-start gap-3 rounded-lg border p-3"
            >
              <Checkbox
                aria-label={topic.name}
                checked={selected.includes(topic.id)}
                onCheckedChange={(checked) =>
                  setSelected((values) =>
                    checked
                      ? [...values, topic.id]
                      : values.filter((id) => id !== topic.id)
                  )
                }
              />
              <span className="min-w-0 break-words">
                {topic.name}
                <span className="block text-sm text-muted-foreground">
                  {
                    subjects.find((subject) => subject.id === topic.subject_id)
                      ?.name
                  }
                </span>
              </span>
            </label>
          ))}
          <StartStudy
            key={chosen.join(",")}
            topicIds={chosen}
            topics={available.filter((topic) => chosen.includes(topic.id))}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}
