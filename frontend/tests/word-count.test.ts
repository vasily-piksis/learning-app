import { expect, test } from "vitest"
import fixture from "../../tests/fixtures/word-count-v1.json"
import { countWords, WORD_COUNT_VERSION } from "../src/lib/word-count"

test.each(fixture.cases)("Unicode count for $text", ({ text, count }) => {
  expect(countWords(text)).toBe(count)
})
test("uses the shared counter version", () => {
  expect(WORD_COUNT_VERSION).toBe(fixture.version)
})
