"""API / attendance tests."""

from datetime import datetime

from app import models


def test_stats_empty(logged_in_client):
    resp = logged_in_client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["student_count"] == 0
    assert data["today_attendance"] == 0
    assert data["total_records"] == 0
    assert data["today_list"] == []
    assert data["photo_counts"] == {}
    assert data["this_week"] == 0


def test_attendance_empty(logged_in_client):
    resp = logged_in_client.get("/api/attendance")
    assert resp.status_code == 200
    assert resp.get_json()["records"] == []


def test_mark_attendance_and_dedupe(db, logged_in_client):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    first = models.mark_attendance(db, 1, "RAHUL", date_str, time_str)
    assert first is True
    # Duplicate (same user, student, date) is rejected atomically.
    second = models.mark_attendance(db, 1, "RAHUL", date_str, time_str)
    assert second is False

    resp = logged_in_client.get("/api/stats")
    data = resp.get_json()
    assert data["today_attendance"] == 1
    assert data["total_records"] == 1
    assert "RAHUL" in data["today_list"]

    resp = logged_in_client.get("/api/attendance")
    records = resp.get_json()["records"]
    assert len(records) == 1
    assert records[0]["Name"] == "RAHUL"


def test_attendance_is_scoped_per_user(db, logged_in_client):
    # user 2 should not see user 1's records
    from app.database import users

    sess = db.session
    user2 = sess.execute(
        users.insert().values(
            username="other",
            password_hash="x",
            display_name="Other",
            school="",
        )
    )
    sess.commit()

    now = datetime.now()
    models.mark_attendance(db, user2.lastrowid, "SOMEONE", now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"))

    resp = logged_in_client.get("/api/attendance")
    assert resp.get_json()["records"] == []


def test_clear_today(db, logged_in_client):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    models.mark_attendance(db, 1, "A", date_str, "10:00:00")
    models.mark_attendance(db, 1, "B", date_str, "10:01:00")

    resp = logged_in_client.post("/api/attendance/clear_today")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "cleared"

    data = logged_in_client.get("/api/stats").get_json()
    assert data["today_attendance"] == 0
    assert data["total_records"] == 0


def test_weekly_trend(db, logged_in_client):
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    models.mark_attendance(db, 1, "RAHUL", date_str, "10:00:00")
    models.mark_attendance(db, 1, "PRIYA", date_str, "10:02:00")

    resp = logged_in_client.get("/api/attendance/weekly")
    assert resp.status_code == 200
    weekly = resp.get_json()["weekly"]
    day_name = now.strftime("%A")
    assert weekly.get(day_name) == 2


def test_export_csv(logged_in_client):
    resp = logged_in_client.get("/api/attendance/export.csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    body = resp.get_data(as_text=True)
    assert body.startswith("Name,Date,Time")


def test_recognize_requires_image(logged_in_client):
    resp = logged_in_client.post("/api/recognize", json={"image": ""})
    assert resp.status_code == 400
    assert resp.get_json()["faces"] == []


def test_recognize_bad_base64(logged_in_client):
    resp = logged_in_client.post("/api/recognize", json={"image": "not-base64@@@"})
    assert resp.status_code in (400, 500)


def test_recognize_blank_image_no_faces(logged_in_client):
    import base64

    import numpy as np

    blank = np.zeros((300, 300, 3), dtype=np.uint8)
    import cv2

    ok, buf = cv2.imencode(".jpg", blank)
    data_url = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    resp = logged_in_client.post("/api/recognize", json={"image": data_url})
    assert resp.status_code == 200
    assert resp.get_json()["faces"] == []


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"


def test_security_headers_present(logged_in_client):
    resp = logged_in_client.get("/dashboard")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy" in resp.headers
