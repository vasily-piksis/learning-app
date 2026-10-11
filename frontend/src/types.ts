export type Mode = "flashcard" | "quiz"
export type User = {
  id: number
  username: string
  display_name: string
  csrf_token: string
}
export type Subject = { id: number; name: string; topic_count: number }
export type Topic = {
  id: number
  subject_id: number
  name: string
  version: number
  card_count: number
  document_count: number
}
export type Document = {
  id: number
  topic_id: number
  name: string
  mime: string
  size: number
  page_count: number
  status: string
  job_id: number
  error: string | null
  warnings?: { page: number; messages: string[] }[]
  source_url?: string | null
  language?: string | null
  is_generated?: boolean | null
  used_for_questions?: boolean
  duplicate?: boolean
}
export type Source = {
  document_id: number
  page: number
  name?: string
  url?: string
  start_seconds?: number
  end_seconds?: number
}
export type Card = {
  id: number
  topic_id: number
  question: string
  answer?: string
  mode: Mode
  options: string[]
  correct_index?: number | null
  version: number
  status: string
  sources: Source[]
  revealed?: boolean
  job_id?: number
  language?: string | null
  target_language?: string | null
}
export type Job = {
  id: number
  kind: string
  status: string
  error: string | null
  created: string
  topic_ids?: number[]
  result: {
    card_ids?: number[]
    warnings?: string[]
    explanation_id?: number
    text?: string
    example?: string | null
    sources?: Source[]
  } | null
}
export type StudySession = {
  review?: {
    position: number
    card: Card
    correct: boolean
    choice: number | null
    remembered: boolean | null
  }[]
  id: number
  topic_ids: number[]
  topic_names: string[]
  mode: Mode
  position: number
  status: string
  count: number
  answered: number
  correct: number
  created: string
  card?: Card | null
}
export type Feedback = {
  session_id: number
  position: number
  correct: boolean
  card: Card
  next_position: number
}
export type Explanation = {
  id: number
  question: string
  parent_id: number | null
  text: string
  example: string | null
  sources: Source[]
}
