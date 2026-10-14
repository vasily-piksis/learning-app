import type { Card } from "@/types"
import { QuestionImageView } from "./QuestionImages"
export default function ExerciseSolution({ card }: { card: Card }) {
  return (
    <>
      {card.answer ? (
        <p className="whitespace-pre-wrap">{card.answer}</p>
      ) : null}
      <QuestionImageView image={card.images?.answer} />
    </>
  )
}
