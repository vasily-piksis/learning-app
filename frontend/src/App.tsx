import { t, useLocale } from "@/i18n"
import LanguageSwitcher from "@/components/LanguageSwitcher"
import { useEffect, useState } from "react"
import {
  BookOpen,
  LibraryBig,
  History as HistoryIcon,
  LogOut,
  Heart,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Toaster } from "@/components/ui/sonner"
import { ErrorNotice, Loading } from "@/components/shared"
import { api, APIError, errorText, setCsrf, navigate } from "@/api"
import type { User } from "@/types"
import Login from "@/features/Login"
import Library from "@/features/Library"
import Generation, { GenerationResult } from "@/features/Generation"
import Topic from "@/features/Topic"
import { Preparation } from "@/features/StartStudy"
import Study from "@/features/Study"
import History from "@/features/History"
import Profile from "@/features/Profile"

function useRoute() {
  const [hash, setHash] = useState(
    () => window.location.hash.slice(1) || "library"
  )
  useEffect(() => {
    const change = () => setHash(window.location.hash.slice(1) || "library")
    window.addEventListener("hashchange", change)
    return () => window.removeEventListener("hashchange", change)
  }, [])
  return hash
}
export default function App() {
  const locale = useLocale()
  useEffect(() => {
    document.documentElement.lang = locale
    document.title = t("Семейная библиотека")
  }, [locale])
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState<string | null>(null),
    [authRevision, setAuthRevision] = useState(0)
  const route = useRoute(),
    [page, kind, id, section, cardId] = route.split("?")[0].split("/")
  useEffect(() => {
    let alive = true
    api<User>("/auth/me")
      .then((u) => {
        if (alive) {
          setUser(u)
          setCsrf(u.csrf_token)
        }
      })
      .catch((e) => {
        if (alive && !(e instanceof APIError && e.status === 401))
          setError(errorText(e))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [authRevision])
  useEffect(() => {
    const expired = () => {
      setUser(null)
      setCsrf("")
      navigate("library")
    }
    window.addEventListener("auth-expired", expired)
    return () => window.removeEventListener("auth-expired", expired)
  }, [])
  if (loading)
    return (
      <main className="startup">
        <Loading />
      </main>
    )
  if (!user && error)
    return (
      <main className="startup">
        <ErrorNotice
          message={error}
          retry={() => {
            setError(null)
            setLoading(true)
            setAuthRevision((n) => n + 1)
          }}
        />
      </main>
    )
  if (!user)
    return (
      <Login
        onLogin={(u) => {
          setUser(u)
          setCsrf(u.csrf_token)
          setError(null)
        }}
      />
    )
  return (
    <div className="app-shell">
      <a
        href="#main"
        className="skip-link"
        onClick={(event) => {
          event.preventDefault()
          document.getElementById("main")?.focus()
        }}
      >
        {t("К содержимому")}
      </a>
      <header className="app-header">
        <a className="brand" href="#library">
          <span className="brand-mark">
            <BookOpen />
          </span>
          {t("учиться")}
          <span className="brand-dot">.</span>
        </a>
        <nav className="main-nav" aria-label={t("Основная навигация")}>
          {[
            { key: "library", label: t("Библиотека"), icon: LibraryBig },
            { key: "history", label: t("История"), icon: HistoryIcon },
          ].map((item) => (
            <a
              key={item.key}
              href={`#${item.key}`}
              className={page === item.key ? "active" : ""}
              aria-current={page === item.key ? "page" : undefined}
            >
              <item.icon className="size-4" />
              <span>{item.label}</span>
            </a>
          ))}
        </nav>
        <div className="account">
          <LanguageSwitcher />
          <Profile
            user={user}
            onChanged={(value) => {
              setUser(value)
              setCsrf(value.csrf_token)
            }}
          />
          <Button
            size="icon"
            variant="ghost"
            aria-label={t("Выйти")}
            onClick={async () => {
              try {
                await api("/auth/logout", "POST")
                setUser(null)
                setCsrf("")
                navigate("library")
              } catch (e) {
                setError(errorText(e))
              }
            }}
          >
            <LogOut />
          </Button>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="main-content">
        <ErrorNotice message={error} />
        {page === "generation" ||
        (page === "generate" &&
          new URLSearchParams(route.split("?")[1]).has("job")) ? (
          <GenerationResult
            key={route}
            id={Number(
              page === "generation"
                ? kind
                : new URLSearchParams(route.split("?")[1]).get("job")
            )}
          />
        ) : page === "prepare" ? (
          <Preparation key={kind} id={Number(kind)} />
        ) : page === "library" && kind === "topic" ? (
          <Topic
            key={`${id}/${section}/${cardId}`}
            id={Number(id)}
            section={section}
            cardId={cardId ? Number(cardId) : undefined}
          />
        ) : page === "generate" ? (
          <Generation
            key={route}
            initialTopics={
              new URLSearchParams(route.split("?")[1])
                .get("topics")
                ?.split(",")
                .map(Number)
                .filter(Number.isFinite) || []
            }
          />
        ) : page === "study" ? (
          <Study key={kind} id={Number(kind)} />
        ) : page === "history" ? (
          <History />
        ) : (
          <Library
            subjectId={kind === "subject" ? Number(id) : undefined}
            displayName={user.display_name}
          />
        )}
      </main>
      <footer className="app-footer">
        <span>
          <Heart className="size-3.5" />
          {t("Учимся в своём темпе")}
        </span>
        <span>{t("Семейная библиотека")}</span>
      </footer>
      <Toaster position="top-center" richColors />
    </div>
  )
}
