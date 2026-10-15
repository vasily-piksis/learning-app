import profile from "../../../backend/app/word-count-profile.json"

export const WORD_COUNT_UNICODE_VERSION = profile.unicode_category_version
function category(char: string): string {
  const point = char.codePointAt(0)!
  let low = 0,
    high = profile.ranges.length - 1
  while (low <= high) {
    const middle = (low + high) >>> 1
    const [start, end, kind] = profile.ranges[middle] as [
      number,
      number,
      string,
    ]
    if (point < start) high = middle - 1
    else if (point > end) low = middle + 1
    else return kind
  }
  return ""
}

export const WORD_COUNT_VERSION = 1

/** NFC affects counting only: callers retain the original submitted text. */
export function countWords(text: string): number {
  const chars = Array.from(text.normalize("NFC"))
  let count = 0,
    active = false,
    letter = false
  for (let i = 0; i < chars.length; i++) {
    const char = chars[i]
    if (["L", "N"].includes(category(char))) {
      if (!active) count++
      active = true
      letter = category(char) === "L"
    } else if (category(char) === "M" && active && letter) {
      continue
    } else if (
      "'’‐‑-".includes(char) &&
      active &&
      i + 1 < chars.length &&
      ["L", "N"].includes(category(chars[i + 1]))
    ) {
      letter = false
    } else {
      active = false
      letter = false
    }
  }
  return count
}
