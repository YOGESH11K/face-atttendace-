"""Admin user-management API tests."""

import pytest

from app import models


@pytest.fixture()
def admin_client(client, db):
    from conftest import register

    register(client, username="boss", display="Boss")
    user = models.get_user_by_username(db, "boss")
    models.set_user_role(db, user.id, "admin")
    client.post("/login", data={"username": "boss", "password": "StrongPass1"})
    return client


def test_users_api_requires_admin(logged_in_client):
    resp = logged_in_client.get("/api/users")
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "forbidden"

    resp = logged_in_client.post(
        "/api/users",
        json={"username": "hacker", "password": "StrongPass1", "display_name": "Hacker"},
    )
    assert resp.status_code == 403


def test_users_api_requires_login(client):
    resp = client.get("/api/users")
    assert resp.status_code == 401


def test_list_users(admin_client, db):
    models.create_user(db, "teacher2", "StrongPass1", "Second Teacher", "School B")
    resp = admin_client.get("/api/users")
    assert resp.status_code == 200
    users = resp.get_json()["users"]
    assert any(u["username"] == "boss" and u["role"] == "admin" for u in users)
    assert any(u["username"] == "teacher2" and u["role"] == "teacher" for u in users)
    # password hashes must never be exposed
    assert all("password" not in u for u in users)
    assert all("password_hash" not in u for u in users)


def test_create_user(admin_client):
    resp = admin_client.post(
        "/api/users",
        json={
            "username": "newteacher",
            "password": "StrongPass1",
            "display_name": "New Teacher",
            "school": "School C",
            "role": "teacher",
        },
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["ok"] is True
    assert data["username"] == "newteacher"

    # the new user can actually log in
    admin_client.post("/logout")
    resp = admin_client.post(
        "/login", data={"username": "newteacher", "password": "StrongPass1"}
    )
    assert resp.status_code == 302


def test_create_user_validation(admin_client):
    resp = admin_client.post(
        "/api/users",
        json={"username": "ab", "password": "StrongPass1", "display_name": "Short"},
    )
    assert resp.status_code == 400

    resp = admin_client.post(
        "/api/users",
        json={"username": "bad name!", "password": "StrongPass1", "display_name": "Bad"},
    )
    assert resp.status_code == 400

    resp = admin_client.post(
        "/api/users",
        json={"username": "validuser", "password": "short", "display_name": "Ok"},
    )
    assert resp.status_code == 400

    resp = admin_client.post(
        "/api/users",
        json={"username": "validuser", "password": "StrongPass1", "display_name": ""},
    )
    assert resp.status_code == 400


def test_create_user_duplicate(admin_client):
    resp = admin_client.post(
        "/api/users",
        json={"username": "boss", "password": "StrongPass1", "display_name": "Dup"},
    )
    assert resp.status_code == 409


def test_set_user_role(admin_client, db):
    user_id = models.create_user(db, "target", "StrongPass1", "Target User", "")
    resp = admin_client.post(
        f"/api/users/{user_id}/role", json={"role": "admin"}
    )
    assert resp.status_code == 200
    assert models.get_user_role(db, user_id) == "admin"

    resp = admin_client.post(
        f"/api/users/{user_id}/role", json={"role": "teacher"}
    )
    assert resp.status_code == 200
    assert models.get_user_role(db, user_id) == "teacher"


def test_set_user_role_bad_role(admin_client, db):
    user_id = models.create_user(db, "target2", "StrongPass1", "Target Two", "")
    resp = admin_client.post(
        f"/api/users/{user_id}/role", json={"role": "superuser"}
    )
    assert resp.status_code == 400
    assert models.get_user_role(db, user_id) == "teacher"


def test_set_user_role_not_found(admin_client):
    resp = admin_client.post("/api/users/99999/role", json={"role": "admin"})
    assert resp.status_code == 404


def test_admin_cannot_demote_self(admin_client):
    boss = models.get_user_by_username(admin_client.application.db, "boss")
    resp = admin_client.post(
        f"/api/users/{boss.id}/role", json={"role": "teacher"}
    )
    assert resp.status_code == 400
