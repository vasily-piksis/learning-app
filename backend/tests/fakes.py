from app.schemas import ExplanationResult, Extraction, Generated, GeneratedCard, SourceRef


class FixtureAI:
    """Only substitutes the paid external AI boundary; never installed in production."""

    def __init__(self):
        self.inputs = []
        self.invalid_source = False
        self.fail_page = None

    def extract(self, path, mime, page_number, local_text):
        if self.fail_page == page_number:
            raise ValueError("Страница не обработана")
        return Extraction(page=page_number, text=local_text or "Учебный текст о Ниле", warnings=[])

    def generate(self, topic_id, sources, mode, count):
        self.inputs.append((topic_id, sources))
        ref = SourceRef(
            document_id=999999 if self.invalid_source else sources[0]["document_id"],
            page=sources[0]["page"],
        )
        return Generated(
            cards=[
                GeneratedCard(
                    topic_id=topic_id,
                    question=f"Вопрос {i}",
                    answer="Нил",
                    mode=mode,
                    options=["Нил", "Волга", "Дон"] if mode == "quiz" else [],
                    correct_index=0 if mode == "quiz" else None,
                    sources=[ref],
                )
                for i in range(count)
            ],
            insufficient_reason=None,
        )

    def explain(self, snapshot, question, history):
        self.inputs.append((snapshot, question, history))
        return ExplanationResult(
            text="Нил — река, рядом с которой жили люди.",
            example="Аналогия: река как дорога для лодок.",
            sources=[SourceRef(document_id=snapshot["sources"][0]["document_id"], page=1)],
        )


def ready_document(client, app, topic, pages=1):
    from app.jobs import run_job
    from conftest import pdf_bytes

    document = client.post(
        f"/api/topics/{topic}/documents", files={"file": ("lesson.pdf", pdf_bytes(pages))}
    ).json()
    run_job(app.state.db, app.state.ai, document["job_id"])
    return document
