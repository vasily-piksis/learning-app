import type { Card } from "@/types"
export default function ExerciseSolution({ card }: { card: Card }) {
  return card.answer ? (
    <p className="whitespace-pre-wrap">{card.answer}</p>
  ) : null
}
