import { expect, test } from "vitest"
import { gapProjection } from "../src/lib/exercises"
import type { Card, FreeResponseExercise, GapExercise } from "../src/types"

test.each([
  ["ß", "ss"],
  ["ΟΣ", "οσ"],
  ["Ꭰ", "ꭰ"],
])(
  "gap projection deduplicates Unicode casefold equivalents %s/%s across different combinations",
  (first, second) => {
    const exercise: GapExercise = {
      segments: [{ gap_id: "a" }, { text: " " }, { gap_id: "b" }],
      gaps: [
        { id: "a", accepted_answers: [] },
        { id: "b", accepted_answers: [] },
      ],
      accepted_combinations: [
        [first, "x"],
        [second, "y"],
      ],
      case_sensitive: false,
    }
    expect(gapProjection(exercise).gaps[0].accepted_answers).toEqual([first])
    expect(
      gapProjection({ ...exercise, case_sensitive: true }).gaps[0]
        .accepted_answers
    ).toEqual([first, second])
  }
)

test("Python whitespace is collapsed while a BOM remains significant", () => {
  const make = (first: string, second: string): GapExercise => ({
    segments: [{ gap_id: "a" }, { text: " " }, { gap_id: "b" }],
    gaps: [
      { id: "a", accepted_answers: [] },
      { id: "b", accepted_answers: [] },
    ],
    accepted_combinations: [
      [first, "x"],
      [second, "y"],
    ],
    case_sensitive: false,
  })
  expect(
    gapProjection(make("a\u0085b", "a b")).gaps[0].accepted_answers
  ).toHaveLength(1)
  expect(
    gapProjection(make("\ufeffword", "word")).gaps[0].accepted_answers
  ).toHaveLength(2)
})

const freeExercise: FreeResponseExercise = {
  goal: "content",
  language: "lt",
  level: null,
  min_words: null,
  max_words: null,
  model_answer: "An example",
  rubric: [{ id: "facts", label: "Facts", weight: 100 }],
  expected_points: [
    {
      id: "point",
      text: "An example",
      essential: true,
      sources: [{ document_id: 1, page: 1 }],
    },
  ],
  source_fragments: [
    { source: { document_id: 1, page: 1 }, text: "An example" },
  ],
}
const freeCard: Card = {
  id: 1,
  topic_id: 1,
  question: "Explain",
  mode: "quiz",
  options: [],
  version: 1,
  status: "saved",
  sources: [],
  question_type: "free_response",
  exercise: freeExercise,
}

test("free response displays its example as the solution", async () => {
  const { exerciseSolution } = await import("../src/lib/exercises")
  expect(exerciseSolution("free_response", freeExercise)).toBe("An example")
})

test("free response submission display preserves the raw answer", async () => {
  const { submissionText } = await import("../src/lib/exercises")
  expect(
    submissionText(freeCard, {
      free_text: "  Raw Ą text\n",
      audio_answer_id: null,
    })
  ).toBe("  Raw Ą text\n")
})
