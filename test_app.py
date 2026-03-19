import pytest
from app import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_hello_returns_greeting(client):
    response = client.get("/hello")
    assert response.status_code == 200
    assert response.get_json() == {"message": "Hello, World!"}


def test_hello_method_not_allowed(client):
    response = client.post("/hello")
    assert response.status_code == 405


def test_echo_returns_body(client):
    payload = {"key": "value", "number": 42}
    response = client.post("/echo", json=payload)
    assert response.status_code == 200
    assert response.get_json() == payload


def test_echo_empty_object(client):
    response = client.post("/echo", json={})
    assert response.status_code == 200
    assert response.get_json() == {}


def test_echo_nested_json(client):
    payload = {"user": {"name": "Alice", "roles": ["admin", "editor"]}}
    response = client.post("/echo", json=payload)
    assert response.status_code == 200
    assert response.get_json() == payload


def test_echo_invalid_json(client):
    response = client.post("/echo", data="not json", content_type="application/json")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_echo_missing_body(client):
    response = client.post("/echo")
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_echo_get_not_allowed(client):
    response = client.get("/echo")
    assert response.status_code == 405
