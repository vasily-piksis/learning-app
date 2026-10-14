import pytest
from app.jobs import run_job
from test_exercise_generation import setup_generation


@pytest.mark.parametrize(
    "kind,new_exercise,expected",
    [
        ("written", {"accepted_answers": ["pilietis"], "case_sensitive": False}, "pilietis"),
        (
            "matching",
            {"pairs": [{"left": "a", "right": "1"}, {"left": "b", "right": "2"}]},
            "a → 1\nb → 2",
        ),
        ("ordering", {"tokens": ["I", "can"], "accepted_orders": [["I", "can"]]}, "I can"),
    ],
)
def test_editing_exercise_changes_derived_answer_and_keeps_type(
    client, app, kind, new_exercise, expected
):
    topic = setup_generation(client, app)
    job = client.post(
        "/api/generate",
        json={
            "topic_ids": [topic],
            "count": 1,
            "question_types": [kind],
            "practice_goal": "language",
        },
    ).json()
    run_job(app.state.db, app.state.ai, job["id"])
    cards = client.get(f"/api/cards?job_id={job['id']}").json()
    assert len(cards) == 1, client.get(f"/api/jobs/{job['id']}").json()
    card = cards[0]
    body = {"question": "Updated question", "exercise": new_exercise, "version": card["version"]}
    result = client.patch(f"/api/cards/{card['id']}", json=body)
    assert result.status_code == 200, result.text
    assert result.json()["answer"] == expected and result.json()["question_type"] == kind
    assert result.json()["version"] == card["version"] + 1
    assert client.patch(f"/api/cards/{card['id']}", json=body).status_code == 409
    fresh = {**body, "version": result.json()["version"]}
    assert (
        client.patch(
            f"/api/cards/{card['id']}", json={**fresh, "answer": "contradictory"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/cards/{card['id']}", json={**fresh, "question_type": "choice"}
        ).status_code
        == 422
    )
