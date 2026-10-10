import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings
from app.cli import create_user


@pytest.fixture
def app(tmp_path):
    instance = create_app(Settings(data_dir=tmp_path, app_origin="http://testserver", cookie_secure=False), worker=False)
    create_user(instance.state.db, "child", "Дочка", "strong-password")
    create_user(instance.state.db, "parent", "Папа", "parent-password")
    return instance


@pytest.fixture
def client(app):
    with TestClient(app) as value:
        response = value.post("/api/auth/login", json={"username": "child", "password": "strong-password"}, headers={"Origin": "http://testserver"})
        value.headers.update({"Origin": "http://testserver", "X-CSRF-Token": response.json()["csrf_token"]})
        yield value


def make_topic(client, name="Древний Египет"):
    subject = client.post("/api/subjects", json={"name": "История"})
    assert subject.status_code == 200, subject.text
    topic = client.post("/api/topics", json={"name": name, "subject_id": subject.json()["id"]})
    assert topic.status_code == 200, topic.text
    return topic.json()["id"]


def pdf_bytes(pages=1, encrypted=False):
    import pymupdf
    pdf = pymupdf.open()
    for _ in range(pages):
        page = pdf.new_page()
        page.insert_text((50, 50), "Egypt is on the Nile. Pharaoh ruled Egypt.")
    if encrypted:
        return pdf.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="reader")
    return pdf.tobytes()
