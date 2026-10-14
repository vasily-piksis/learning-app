import { expect, test } from "vitest"
import { gapProjection } from "../src/lib/exercises"
import type { GapExercise } from "../src/types"

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
