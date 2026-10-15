import { t } from "@/i18n"
export function wordTarget(
  count: number,
  min: number | null,
  max: number | null
) {
  if (min !== null && max !== null)
    return t("Слов: {count} · цель {min}–{max}", { count, min, max })
  if (min !== null) return t("Слов: {count} · не менее {min}", { count, min })
  if (max !== null) return t("Слов: {count} · не более {max}", { count, max })
  return t("Слов: {count}", { count })
}
