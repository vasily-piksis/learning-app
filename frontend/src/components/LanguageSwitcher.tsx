import { getLocale, setLocale, t, type Locale } from "@/i18n"

export default function LanguageSwitcher() {
  return (
    <select
      aria-label={t("Язык интерфейса")}
      className="h-8 max-w-28 rounded-lg border bg-background px-2 text-sm"
      value={getLocale()}
      onChange={(event) => setLocale(event.target.value as Locale)}
    >
      <option value="pl">Polski</option>
      <option value="en">English</option>
      <option value="ru">Русский</option>
    </select>
  )
}
