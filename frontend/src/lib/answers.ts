import type { Card } from "@/types"
export function correctIndices(card: Card): number[] {
  return card.correct_indices?.length
    ? card.correct_indices
    : card.correct_index == null
      ? []
      : [card.correct_index]
}
