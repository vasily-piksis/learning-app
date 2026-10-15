export type QuestionType =
  | "choice"
  | "written"
  | "gap"
  | "ending"
  | "matching"
  | "ordering"
  | "free_response"
export type FreeResponseGoal = "content" | "language"
export type FreeResponseLevel = "A1" | "A2" | "B1" | "B2" | "C1" | "C2"
export type FreeResponseSourceRef = { document_id: number; page: number }
export type RubricCriterion = { id: string; label: string; weight: number }
export type ExpectedPoint = {
  id: string
  text: string
  essential: boolean
  sources: FreeResponseSourceRef[]
}
export type FreeResponseExercise = {
  goal: FreeResponseGoal
  language: string
  level: FreeResponseLevel | null
  min_words: number | null
  max_words: number | null
  model_answer: string
  rubric: RubricCriterion[]
  expected_points: ExpectedPoint[]
  source_fragments: { source: FreeResponseSourceRef; text: string }[]
}
export type PublicFreeResponseExercise = Pick<
  FreeResponseExercise,
  "goal" | "language" | "level" | "min_words" | "max_words"
>
export type RubricScore = {
  criterion_id: string
  score: number
  explanation: string
}
export type TextEvidence = {
  kind: "text"
  source: FreeResponseSourceRef
  quote: string
}
export type PointCheck = {
  point_id: string
  met: boolean
  evidence: TextEvidence[]
}
export type Correction = {
  original: string
  suggested: string
  explanation: string
}
export type EvaluationFeedback = {
  rubric_scores: RubricScore[]
  point_checks: PointCheck[]
  language_match: boolean
  corrections: Correction[]
  summary: string
  suggestions: string[]
}
export type FreeResponseEvaluation = EvaluationFeedback & {
  assessability: "assessable" | "insufficient_context"
  reason: string | null
}
export type EvaluationGrade = EvaluationFeedback & {
  score: number
  correct: boolean
  word_count: number
  word_count_version: 1
  word_limit: { min: number | null; max: number | null; met: boolean }
}
export type VoiceMetadata = {
  original_transcript: string
  original_word_count: number
  was_edited: boolean
}
export type StoredEvaluationGrade = EvaluationGrade & {
  version: 2
  evaluation_id: number
} & (
    | { input_method: "text"; voice: null }
    | { input_method: "voice"; voice: VoiceMetadata }
  )
export type GapExercise = {
  segments: ({ text: string } | { gap_id: string })[]
  gaps: { id: string; accepted_answers: string[] }[]
  case_sensitive: boolean
  accepted_combinations: string[][]
}
export type FullExercise =
  | FreeResponseExercise
  | { accepted_answers: string[]; case_sensitive: boolean }
  | GapExercise
  | { pairs: { left: string; right: string }[] }
  | { tokens: string[]; accepted_orders: string[][] }
export type ExerciseItem = { id: string; text: string }
export type PublicExercise =
  | PublicFreeResponseExercise
  | { case_sensitive: boolean }
  | {
      segments: GapExercise["segments"]
      gaps: { id: string }[]
      case_sensitive: boolean
    }
  | { left: ExerciseItem[]; right: ExerciseItem[] }
  | { tokens: ExerciseItem[] }
export type ExerciseSubmission =
  | { free_text: string; audio_answer_id?: string | null }
  | { text: string }
  | { gap_answers: Record<string, string> }
  | { pairs: { left_id: string; right_id: string }[] }
  | { order: string[] }
export type GradePart = { id: string; correct: boolean }
export type MethodAvailability = {
  ready_count: number
  draft_count: number
  needs_options_count: number
  preparation_job_id: number | null
  preparation_status: string | null
  has_ready_materials: boolean
  last_outcome: {
    method: string
    source_fingerprint: string
    reason: string
    stale: boolean
  } | null
}
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
  practice_availability?: Record<string, MethodAvailability>
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
  available?: boolean
  page: number
  name?: string
  url?: string
  start_seconds?: number
  end_seconds?: number
}
export type ImageSlot = "question" | "answer"
export type QuestionImage = {
  asset_id: string
  url: string
  alt: string
  width: number
  height: number
  mime: string
  origin: "upload" | "generated"
}
export type ImageUpdates = Partial<
  Record<ImageSlot, { asset_id: string | null; alt: string }>
>
export type ImageCandidate = QuestionImage & {
  id: string
  slot: ImageSlot
  stage: "draft" | "obsolete"
  can_apply: boolean
  target_version: number
}
export type Card = {
  images?: Partial<Record<ImageSlot, QuestionImage>>
  question_type?: QuestionType
  exercise?: FullExercise | PublicExercise | null
  id: number
  topic_id: number
  question: string
  answer?: string
  mode: Mode
  options: string[]
  correct_index?: number | null
  correct_indices?: number[]
  multiple_answers?: boolean
  version: number
  status: string
  sources: Source[]
  revealed?: boolean
  job_id?: number
  language?: string | null
  target_language?: string | null
}
export type QuestionCandidate = {
  topic_id: number
  question_type: QuestionType
  question: string
  answer: string
  mode: Mode
  options: string[]
  correct_index: number | null
  correct_indices: number[]
  sources: { document_id: number; page: number }[]
  language: string | null
  exercise: FullExercise | null
}
export type ImageGenerationAvailability = {
  status:
    | "disabled"
    | "missing_model"
    | "invalid_model"
    | "missing_key"
    | "invalid_timezone"
    | "invalid_limit"
    | "ready"
  enabled: boolean
  model: string | null
  settings: { n: number; size: string; quality: string; output_format: string }
  access_status: "denied" | "confirmed" | "unverified"
  limit: number
  used: number | null
  remaining: number
  timezone: string
  next_reset_at: string | null
}
export type Job = {
  id: number
  kind: string
  card_id?: number
  slot?: ImageSlot
  status: string
  error: string | null
  created: string
  topic_ids?: number[]
  result: {
    card_ids?: number[]
    warnings?: string[]
    model_warnings?: string[]
    explanation_id?: number
    text?: string
    example?: string | null
    sources?: Source[]
    unsupported_types?: { question_type: QuestionType; reason: string }[]
    candidate?: QuestionCandidate | null
    card_id?: number
    base_version?: number
    insufficient_reason?: string | null
    applied_version?: number
    applied_result?: Card
    candidates?: {
      card_id: number
      version: number
      options: string[]
      correct_index: number | null
      correct_indices: number[]
    }[]
    applied_card_ids?: number[]
    discarded?: boolean
  } | null
}
export type StudySession = {
  question_types?: Record<string, number>
  practice_method?: string
  review?: {
    position: number
    card: Card
    correct: boolean
    choice: number | null
    choices?: number[]
    submission?: Feedback["submission"]
    parts?: GradePart[]
    message_code?: string | null
    remembered: boolean | null
  }[]
  id: number
  topic_ids: number[]
  topic_names: string[]
  active_topic_ids?: number[]
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
  submission?:
    ExerciseSubmission | { choices: number[] } | { remembered: boolean }
  parts?: GradePart[]
  message_code?: string | null
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

export type ImageGenerationJob = Omit<Job, "result"> & {
  result: {
    candidate?: ImageCandidate
    can_retry_save?: boolean
    applied_asset_id?: string
    discarded?: boolean
  } | null
}
