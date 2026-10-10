from io import BytesIO
from PIL import Image
from conftest import make_topic, pdf_bytes


def test_hierarchy_rename_upload_and_dedup(client, app):
    topic = make_topic(client)
    assert client.patch(f"/api/topics/{topic}", json={"name": "Египет"}).json()["name"] == "Египет"
    data = pdf_bytes()
    route = f"/api/topics/{topic}/documents"
    first = client.post(route, files={"file": ("../../lesson.pdf", data, "application/pdf")})
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "queued"
    second = client.post(route, files={"file": ("another.pdf", data, "application/pdf")})
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get(route).json()) == 1
    assert client.get(f"/api/documents/{first.json()['id']}/download").content == data
    assert len(list((app.state.settings.data_dir / "files").iterdir())) == 1
    another = make_topic(client, "Средние века")
    assert client.post(f"/api/topics/{another}/documents", files={"file": ("x.pdf", data)}).json()["id"] != first.json()["id"]
    assert client.get(f"/api/topics/{topic}").json()["version"] == 2


def test_actual_file_type_and_limits(client, app):
    route = f"/api/topics/{make_topic(client)}/documents"
    assert client.post(route, files={"file": ("fake.pdf", b"<html>bad</html>", "application/pdf")}).status_code == 422
    assert client.post(route, files={"file": ("locked.pdf", pdf_bytes(encrypted=True))}).status_code == 422
    assert client.post(route, files={"file": ("long.pdf", pdf_bytes(51))}).status_code == 422
    app.state.settings.max_upload_bytes = 1024
    assert client.post(route, files={"file": ("large.pdf", b"x" * 1025)}).status_code == 413
    app.state.settings.max_upload_bytes = 20 * 1024 * 1024
    image = BytesIO()
    Image.new("RGB", (100, 100), "white").save(image, format="PNG")
    response = client.post(route, files={"file": ("looks.pdf", image.getvalue(), "application/pdf")})
    assert response.status_code == 200
    assert response.json()["mime"] == "image/png"


def test_import_survives_reopen(client, app):
    from app.main import create_app
    from fastapi.testclient import TestClient
    route = f"/api/topics/{make_topic(client)}/documents"
    document = client.post(route, files={"file": ("lesson.pdf", pdf_bytes())}).json()
    reopened = create_app(app.state.settings, worker=False)
    with TestClient(reopened) as other:
        other.cookies.update(client.cookies)
        assert other.get(route).json()[0]["id"] == document["id"]
        assert other.get(f"/api/documents/{document['id']}/download").status_code == 200
