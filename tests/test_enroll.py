"""Enrollment endpoint tests."""

import io

import cv2
import numpy as np


def _blank_image_bytes():
    ok, buf = cv2.imencode(".jpg", np.zeros((300, 300, 3), dtype=np.uint8))
    return buf.tobytes()


def test_enroll_capture_requires_name(logged_in_client):
    resp = logged_in_client.post("/api/enroll/capture", json={"image": "data:image/jpeg;base64,"})
    assert resp.status_code == 400
    assert "student name" in resp.get_json()["error"].lower()


def test_enroll_capture_invalid_student_name(logged_in_client):
    resp = logged_in_client.post(
        "/api/enroll/capture",
        json={"student_name": "BAD!@#", "image": "data:image/jpeg;base64,"},
    )
    assert resp.status_code == 400


def test_enroll_upload_no_file(logged_in_client):
    resp = logged_in_client.post(
        "/api/enroll/upload", data={"student_name": "RAHUL"}, content_type="multipart/form-data"
    )
    assert resp.status_code == 400


def test_enroll_upload_invalid_type(logged_in_client):
    resp = logged_in_client.post(
        "/api/enroll/upload",
        data={"student_name": "RAHUL", "file": (io.BytesIO(b"hello"), "evil.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "Invalid file type" in resp.get_json()["error"]


def test_enroll_upload_non_image(logged_in_client):
    resp = logged_in_client.post(
        "/api/enroll/upload",
        data={"student_name": "RAHUL", "file": (io.BytesIO(b"not an image at all"), "x.jpg")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def test_enroll_blank_image_no_face(logged_in_client):
    resp = logged_in_client.post(
        "/api/enroll/upload",
        data={
            "student_name": "RAHUL",
            "file": (io.BytesIO(_blank_image_bytes()), "blank.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    assert "face" in resp.get_json()["error"].lower()


def test_enroll_status_empty(logged_in_client):
    resp = logged_in_client.get("/api/enroll/status")
    data = resp.get_json()
    assert data["enrolled"] is False
    assert data["photos"] == 0
    assert data["students"] == {}


def test_delete_non_existent_photo(logged_in_client):
    resp = logged_in_client.delete("/api/enroll/photo/RAHUL/does-not-exist.jpg")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "not found"


def test_photo_path_traversal_blocked(logged_in_client):
    resp = logged_in_client.get("/api/enroll/photo/..%2F..%2Fetc/passwd")
    assert resp.status_code in (400, 404)


def test_max_photos_per_student(app, db, monkeypatch, user_id):
    import numpy as np

    from app import models
    from app.routes.enroll import _process_enrollment
    from app.utils import ValidationError

    def fake_encode(img, cfg):
        return {"ok": True, "encoding": np.zeros(128, dtype=np.float32)}

    monkeypatch.setattr("app.routes.enroll._encode_for_enrollment", fake_encode)

    user_dir = app.config["DATA_DIR"]
    fake_img = np.zeros((300, 300, 3), dtype=np.uint8)
    with app.app_context():
        for _ in range(app.config["MAX_PHOTOS_PER_STUDENT"]):
            message, count = _process_enrollment(db, user_id, "RAHUL", fake_img, user_dir)
            assert count <= app.config["MAX_PHOTOS_PER_STUDENT"]

        # One more should be rejected by the cap.
        try:
            _process_enrollment(db, user_id, "RAHUL", fake_img, user_dir)
            assert False, "Expected cap rejection"
        except ValidationError as exc:
            assert "Maximum" in str(exc)

    assert models.count_photos_for_student(db, user_id, "RAHUL") == app.config["MAX_PHOTOS_PER_STUDENT"]
