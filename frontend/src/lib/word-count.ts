export const WORD_COUNT_VERSION = 1

/** NFC affects counting only: callers retain the original submitted text. */
export function countWords(text: string): number {
  const chars = Array.from(text.normalize("NFC"))
  let count = 0,
    active = false,
    letter = false
  for (let i = 0; i < chars.length; i++) {
    const char = chars[i]
    if (/[\p{L}\p{N}]/u.test(char)) {
      if (!active) count++
      active = true
      letter = /\p{L}/u.test(char)
    } else if (/\p{M}/u.test(char) && active && letter) {
      continue
    } else if (
      "'’‐‑-".includes(char) &&
      active &&
      i + 1 < chars.length &&
      /[\p{L}\p{N}]/u.test(chars[i + 1])
    ) {
      letter = false
    } else {
      active = false
      letter = false
    }
  }
  return count
}
