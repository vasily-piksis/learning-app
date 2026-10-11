import { useSyncExternalStore } from "react"
import { translations } from "./locales"

export type Locale = "pl" | "en" | "ru"
const listeners = new Set<() => void>()
const storageKey = "learning-ui-language"
let fallback: Locale = "pl"

export function getLocale(): Locale {
  try {
    const saved = localStorage.getItem(storageKey)
    return saved === "pl" || saved === "en" || saved === "ru" ? saved : "pl"
  } catch {
    return fallback
  }
}
export function setLocale(locale: Locale) {
  fallback = locale
  try {
    localStorage.setItem(storageKey, locale)
  } catch {
    /* Private browsing can disallow storage. */
  }
  listeners.forEach((listener) => listener())
}
function subscribe(listener: () => void) {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
export function useLocale() {
  return useSyncExternalStore(subscribe, getLocale, () => "pl" as Locale)
}
export function t(
  source: string,
  vars: Record<string, string | number> = {}
): string {
  const locale = getLocale()
  const value =
    locale === "ru" ? source : translations[source]?.[locale] || source
  return value.replace(/\{(\w+)\}/g, (match, key: string) =>
    String(vars[key] ?? match)
  )
}
export function systemMessage(message: string): string {
  const duplicate = message.match(/^Пропущено повторных вопросов: (\d+)$/)
  return duplicate
    ? t("Пропущено повторных вопросов: {count}", { count: duplicate[1] })
    : t(message)
}
