from test_study import saved_cards


def test_completed_history_retains_answered_cards_and_explanation_jobs(client, app):
    topic, _ = saved_cards(client, app, "quiz", 1)
    session = client.post("/api/study", json={"topic_ids": [topic], "mode": "quiz"}).json()
    client.post(
        f"/api/study/{session['id']}/answer",
        json={"position": 0, "choice": 1, "idempotency_key": "review"},
    )
    job = client.post(f"/api/study/{session['id']}/explain", json={"position": 0}).json()
    details = client.get(f"/api/study/{session['id']}").json()
    assert details["review"][0]["card"]["answer"] == "Нил"
    assert details["review"][0]["correct"] is False
    assert details["review"][0]["choice"] == 1
    pending = client.get(f"/api/study/{session['id']}/explanation-jobs?position=0").json()
    assert pending[0]["id"] == job["id"]
