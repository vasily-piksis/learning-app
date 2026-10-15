import { useEffect, useRef, useState } from "react"
import { api, APIError } from "@/api"
import { t } from "@/i18n"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Field, FieldLabel } from "@/components/ui/field"

export type AudioDTO = {
  audio_answer_id: string
  job_id: number
  status: "queued" | "running" | "ready" | "failed" | "unknown" | "discarded"
  duration: number
  expires_at: string
  original_transcript: string | null
  expected_language: string
  detected_languages: string[]
  language_mismatch: boolean
  recording_available: boolean
  error_code:
    | null
    | "failed"
    | "unknown"
    | "runtime_unavailable"
    | "quota_exceeded"
    | "record_again"
  error: string | null
}
const object = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === "object" && !Array.isArray(v)
export function isAudioDTO(v: unknown, language: string): v is AudioDTO {
  return (
    object(v) &&
    typeof v.audio_answer_id === "string" &&
    /^[a-f0-9]{32}$/.test(v.audio_answer_id) &&
    Number.isSafeInteger(v.job_id) &&
    Number(v.job_id) > 0 &&
    typeof v.status === "string" &&
    ["queued", "running", "ready", "failed", "unknown", "discarded"].includes(
      v.status
    ) &&
    typeof v.duration === "number" &&
    Number.isFinite(v.duration) &&
    v.duration > 0 &&
    v.duration <= 180 &&
    typeof v.expires_at === "string" &&
    v.expires_at.endsWith("Z") &&
    Number.isFinite(Date.parse(v.expires_at)) &&
    (v.original_transcript === null ||
      (typeof v.original_transcript === "string" &&
        Array.from(v.original_transcript).length <= 10000)) &&
    (v.status !== "ready" ||
      (typeof v.original_transcript === "string" &&
        !!v.original_transcript.trim())) &&
    v.expected_language === language &&
    Array.isArray(v.detected_languages) &&
    v.detected_languages.every(
      (l) => typeof l === "string" && /^[a-z]{2,3}$/.test(l)
    ) &&
    typeof v.language_mismatch === "boolean" &&
    typeof v.recording_available === "boolean" &&
    (v.error_code === null ||
      (typeof v.error_code === "string" &&
        [
          "failed",
          "unknown",
          "runtime_unavailable",
          "quota_exceeded",
          "record_again",
        ].includes(v.error_code))) &&
    (v.error === null || typeof v.error === "string")
  )
}
export function recordingMime() {
  if (typeof MediaRecorder === "undefined") return null
  return (
    [
      "audio/webm;codecs=opus",
      "audio/mp4",
      "audio/ogg;codecs=opus",
      "audio/wav",
      "audio/webm",
    ].find((mime) => MediaRecorder.isTypeSupported(mime)) ?? null
  )
}
type Operation = { key: string; retryId: string | null }
export default function VoiceAnswer({
  sessionId,
  position,
  language,
  visible,
  disabled,
  onTranscript,
}: {
  sessionId: number
  position: number
  language: string
  visible: boolean
  disabled: boolean
  onTranscript: (audio: AudioDTO | null) => void
}) {
  const storageKey = `voice-v1:${sessionId}:${position}`
  const [operation, setOperation] = useState<Operation | null>(() => {
    try {
      const v: unknown = JSON.parse(
        sessionStorage.getItem(storageKey) || "null"
      )
      return object(v) &&
        typeof v.key === "string" &&
        v.key.length > 0 &&
        v.key.length <= 80 &&
        (v.retryId === null ||
          (typeof v.retryId === "string" && /^[a-f0-9]{32}$/.test(v.retryId)))
        ? (v as Operation)
        : null
    } catch {
      return null
    }
  })
  const [audio, setAudio] = useState<AudioDTO | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [available, setAvailable] = useState(false)
  const [recording, setRecording] = useState(false)
  const [seconds, setSeconds] = useState(0)
  const [blob, setBlob] = useState<Blob | null>(null)
  const [url, setUrl] = useState("")
  const [busy, setBusy] = useState(false)
  const [uncertain, setUncertain] = useState(false)
  const [error, setError] = useState(false)
  const [ack, setAck] = useState(false)
  const [unavailableRecording, setUnavailableRecording] = useState<
    string | null
  >(null)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const objectURL = useRef("")
  const alive = useRef(true)
  const generation = useRef(0)
  const sending = useRef(false)
  const applied = useRef("")
  const callback = useRef(onTranscript)
  useEffect(() => {
    callback.current = onTranscript
  })
  function releaseURL() {
    if (objectURL.current) URL.revokeObjectURL(objectURL.current)
    objectURL.current = ""
    setUrl("")
  }
  function stop() {
    window.clearInterval(timer.current)
    if (recorder.current?.state === "recording") recorder.current.stop()
    stream.current?.getTracks().forEach((track) => track.stop())
    stream.current = null
    setRecording(false)
  }
  function cancelRecording() {
    generation.current++
    stop()
    releaseURL()
  }
  function accept(value: unknown, expectedId?: string | null) {
    if (
      !isAudioDTO(value, language) ||
      (expectedId && value.audio_answer_id !== expectedId)
    )
      throw new Error("Invalid audio acknowledgement")
    if (!alive.current) return
    setAudio(value.status === "discarded" ? null : value)
    setUncertain(false)
    if (value.status === "ready" && applied.current !== value.audio_answer_id) {
      applied.current = value.audio_answer_id
      callback.current(value)
    }
    return value
  }
  function settle() {
    setOperation(null)
    sessionStorage.removeItem(storageKey)
  }
  async function lookup() {
    const token = generation.current
    const value = await api<unknown>(
      `/study/${sessionId}/audio?position=${position}`
    )
    if (
      !object(value) ||
      typeof value.available !== "boolean" ||
      (value.reason !== null && value.reason !== "runtime_unavailable") ||
      !(value.audio_answer === null || isAudioDTO(value.audio_answer, language))
    )
      throw new Error("Invalid audio lookup")
    if (!alive.current || token !== generation.current) return
    setAvailable(value.available)
    setLoaded(true)
    if (value.audio_answer !== null) accept(value.audio_answer)
    else {
      setAudio(null)
      if (applied.current) {
        applied.current = ""
        callback.current(null)
      }
    }
    return value.audio_answer as AudioDTO | null
  }
  useEffect(() => {
    alive.current = true
    let pending = false
    const load = async () => {
      if (
        pending ||
        sending.current ||
        recorder.current?.state === "recording" ||
        document.visibilityState === "hidden"
      )
        return
      pending = true
      try {
        await lookup()
      } catch {
        if (alive.current) setUncertain(true)
      } finally {
        pending = false
      }
    }
    void load()
    const polling = window.setInterval(() => void load(), 1500)
    const leave = () => {
      if (document.visibilityState === "hidden") {
        generation.current++
        stop()
        releaseURL()
      }
    }
    document.addEventListener("visibilitychange", leave)
    return () => {
      alive.current = false
      cancelRecording()
      if (objectURL.current) URL.revokeObjectURL(objectURL.current)
      window.clearInterval(polling)
      document.removeEventListener("visibilitychange", leave)
    }
    // The owner/card/language are immutable for this keyed exercise instance.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, position, language])
  useEffect(() => {
    return () => {
      cancelRecording()
    }
    // Cancel local resources when the selected method or grading lock changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, disabled])
  async function start() {
    if (sending.current || disabled || operation) return
    sending.current = true
    setBusy(true)
    setError(false)
    const token = ++generation.current
    try {
      const mime = recordingMime()
      if (!mime || !navigator.mediaDevices?.getUserMedia)
        throw new Error("Unsupported")
      if (audio) {
        const result = await api<unknown>(
          `/audio-answers/${audio.audio_answer_id}`,
          "DELETE"
        )
        if (!object(result) || result.discarded !== true)
          throw new Error("Invalid discard")
        setAudio(null)
        applied.current = ""
        callback.current(null)
      }
      const media = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: false,
      })
      if (!alive.current || token !== generation.current) {
        media.getTracks().forEach((track) => track.stop())
        return
      }
      stream.current = media
      const next = new MediaRecorder(media, { mimeType: mime })
      recorder.current = next
      const chunks: Blob[] = []
      next.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data)
      }
      next.onstop = () => {
        if (!alive.current || token !== generation.current) return
        const recorded = new Blob(chunks, { type: next.mimeType || mime })
        if (!recorded.size || recorded.size > 15 * 1024 * 1024) {
          setError(true)
          return
        }
        setBlob(recorded)
        releaseURL()
        objectURL.current = URL.createObjectURL(recorded)
        setUrl(objectURL.current)
      }
      next.onerror = () => {
        stop()
        setError(true)
      }
      releaseURL()
      setBlob(null)
      setSeconds(0)
      next.start()
      setRecording(true)
      const started = Date.now()
      timer.current = window.setInterval(() => {
        const elapsed = Math.min(180, Math.floor((Date.now() - started) / 1000))
        setSeconds(elapsed)
        if (elapsed >= 180) stop()
      }, 250)
    } catch {
      stop()
      setError(true)
    } finally {
      sending.current = false
      setBusy(false)
    }
  }
  async function discard() {
    if (sending.current || disabled || operation) return
    sending.current = true
    setBusy(true)
    try {
      generation.current++
      stop()
      if (audio) {
        const result = await api<unknown>(
          `/audio-answers/${audio.audio_answer_id}`,
          "DELETE"
        )
        if (!object(result) || result.discarded !== true)
          throw new Error("Invalid discard")
      }
      setAudio(null)
      setBlob(null)
      releaseURL()
      applied.current = ""
      callback.current(null)
      setError(false)
    } catch {
      setUncertain(true)
    } finally {
      sending.current = false
      setBusy(false)
    }
  }
  async function send(retry = false) {
    if (sending.current || disabled) return
    sending.current = true
    setBusy(true)
    setUncertain(false)
    try {
      const request = operation || {
        key: crypto.randomUUID(),
        retryId: retry ? audio!.audio_answer_id : null,
      }
      setOperation(request)
      sessionStorage.setItem(storageKey, JSON.stringify(request))
      let value: unknown
      if (request.retryId)
        value = await api<unknown>(
          `/audio-answers/${request.retryId}/retry`,
          "POST",
          { idempotency_key: request.key, acknowledge_extra_cost: true }
        )
      else if (blob) {
        const form = new FormData()
        form.set("position", String(position))
        form.set("idempotency_key", request.key)
        form.set("file", blob, "recording")
        value = await api<unknown>(`/study/${sessionId}/audio`, "POST", form)
      } else {
        value = await lookup()
        if (value === null) {
          settle()
          return
        }
      }
      accept(value, request.retryId)
      settle()
      setAck(false)
      setBlob(null)
      releaseURL()
    } catch (cause) {
      if (alive.current) {
        if (
          cause instanceof APIError &&
          cause.status === 409 &&
          object(cause.detail) &&
          cause.detail.code === "record_again"
        ) {
          settle()
          setAck(false)
          setUnavailableRecording(audio?.audio_answer_id ?? null)
        } else if (
          cause instanceof APIError &&
          [400, 413, 415, 422].includes(cause.status)
        ) {
          settle()
          setError(true)
          setBlob(null)
          releaseURL()
        } else setUncertain(true)
      }
    } finally {
      sending.current = false
      if (alive.current) setBusy(false)
    }
  }
  if (!visible) return null
  const recordingUnavailable = audio?.audio_answer_id === unavailableRecording
  const failed = audio?.status === "failed" || audio?.status === "unknown"
  const pending = audio?.status === "queued" || audio?.status === "running"
  return (
    <section className="flex flex-col gap-3" aria-label={t("Голосовой ответ")}>
      <p>{t("Язык записи: {language}", { language })}</p>
      <p>
        {t(
          "Запись до 180 секунд. Звук удаляется после распознавания и не хранится в истории."
        )}
      </p>
      {!loaded && <p role="status">{t("Проверяем состояние записи")}</p>}
      {loaded && !available && (
        <p role="status">
          {t("Распознавание сейчас недоступно. Можно написать ответ.")}
        </p>
      )}
      {error && (
        <p role="alert">
          {t(
            "Микрофон недоступен или запись не поддерживается. Можно написать ответ."
          )}
        </p>
      )}
      {recording ? (
        <>
          <p role="timer">
            {seconds} / 180 {t("сек.")}
          </p>
          <Button onClick={stop}>{t("Остановить запись")}</Button>
        </>
      ) : (
        <Button
          disabled={
            disabled || busy || !loaded || !available || !!operation || pending
          }
          onClick={() => void start()}
        >
          {t(blob || audio ? "Записать заново" : "Записать")}
        </Button>
      )}
      {(url || (audio?.recording_available && !recordingUnavailable)) && (
        <audio
          controls
          preload="none"
          aria-label={t("Прослушать запись")}
          src={url || `/api/audio-answers/${audio!.audio_answer_id}/recording`}
          className="w-full"
        />
      )}
      {blob && !operation && !recording && (
        <Button
          disabled={disabled || busy || !available}
          onClick={() => void send()}
        >
          {t("Распознать (платно)")}
        </Button>
      )}
      {(blob || audio) && !recording && !operation && (
        <Button
          variant="outline"
          disabled={disabled || busy}
          onClick={() => void discard()}
        >
          {t("Удалить запись")}
        </Button>
      )}
      {blob && !url && !recording && (
        <Button
          variant="outline"
          onClick={() => {
            objectURL.current = URL.createObjectURL(blob)
            setUrl(objectURL.current)
          }}
        >
          {t("Прослушать запись")}
        </Button>
      )}
      {pending && <p role="status">{t("Распознаём запись")}</p>}
      {failed && (
        <p role="status">
          {t(
            recordingUnavailable || audio.error_code === "record_again"
              ? "Запись больше недоступна. Запишите ответ снова."
              : audio.error_code === "quota_exceeded"
                ? "Дневной лимит распознавания исчерпан"
                : audio.error_code === "runtime_unavailable"
                  ? "Распознавание сейчас недоступно. Можно написать ответ."
                  : audio.status === "unknown"
                    ? "Результат неизвестен; запрос мог быть оплачен. Автоматического повтора нет"
                    : "Распознавание не завершено. Оценка не выставлена."
          )}
        </p>
      )}
      {uncertain && (
        <p role="status">
          {t(
            "Не удалось подтвердить распознавание. Проверь состояние снова; новый платный запрос не создаётся."
          )}
        </p>
      )}
      {operation && (
        <Button disabled={busy || disabled} onClick={() => void send()}>
          {t("Проверить распознавание снова")}
        </Button>
      )}
      {failed &&
        audio.recording_available &&
        !recordingUnavailable &&
        !operation && (
          <>
            <Field orientation="horizontal">
              <Checkbox
                id="voice-retry-cost"
                checked={ack}
                disabled={disabled || busy}
                onCheckedChange={(v) => setAck(v === true)}
              />
              <FieldLabel htmlFor="voice-retry-cost">
                {t("Понимаю, что новый запрос может стоить дополнительно")}
              </FieldLabel>
            </Field>
            <Button
              disabled={!ack || disabled || busy || !available}
              onClick={() => void send(true)}
            >
              {t("Повторить распознавание (платно)")}
            </Button>
          </>
        )}
      {audio?.status === "ready" && (
        <>
          <p>
            {t(
              audio.detected_languages.length === 0
                ? "Язык записи не определён"
                : audio.language_mismatch
                  ? "Язык записи отличается от задания"
                  : "Язык записи соответствует заданию"
            )}
          </p>
          <p>
            {t("Распознано: {languages}", {
              languages: audio.detected_languages.join(", ") || "—",
            })}
          </p>
        </>
      )}
    </section>
  )
}
