"""Recognition service unit tests (no real faces needed)."""

import numpy as np

from app.recognition import RecognitionService


def test_consistency_requires_n_frames():
    svc = RecognitionService()
    # first two detections: not consistent
    assert svc.check_consistency(1, "RAHUL", required=3, window=5) is False
    assert svc.check_consistency(1, "RAHUL", required=3, window=5) is False
    # third within window: consistent
    assert svc.check_consistency(1, "RAHUL", required=3, window=5) is True
    # history reset after consistency hit; needs 3 more
    assert svc.check_consistency(1, "RAHUL", required=3, window=5) is False
    assert svc.check_consistency(1, "RAHUL", required=3, window=5) is False
    assert svc.check_consistency(1, "RAHUL", required=3, window=5) is True


def test_consistency_expires_window():
    import time

    svc = RecognitionService()
    assert svc.check_consistency(1, "RAHUL", required=3, window=0.2) is False
    time.sleep(0.25)
    # old timestamps expired, still need 3 fresh
    assert svc.check_consistency(1, "RAHUL", required=3, window=0.2) is False


def test_history_scoped_per_user_and_name():
    svc = RecognitionService()
    assert svc.check_consistency(1, "RAHUL", required=2, window=5) is False
    assert svc.check_consistency(2, "RAHUL", required=2, window=5) is False
    assert svc.check_consistency(1, "PRIYA", required=2, window=5) is False
    assert svc.check_consistency(1, "RAHUL", required=2, window=5) is True


def test_match_returns_best_student(app, user_id):
    svc = RecognitionService()
    db = app.db

    from app import models

    # two fake encodings: student A and student B
    enc_a = np.zeros(128, dtype=np.float32)
    enc_b = np.full(128, 0.3, dtype=np.float32)
    models.add_encoding(db, user_id, "ALICE", enc_a, "ALICE/p1.jpg")
    models.add_encoding(db, user_id, "BOB", enc_b, "BOB/p1.jpg")

    match = svc.match(db, user_id=user_id, encoding=enc_a, tolerance=0.6)
    assert match is not None
    assert match.name == "ALICE"
    assert match.distance == 0.0


def test_match_rejects_beyond_tolerance(app, user_id):
    svc = RecognitionService()
    db = app.db

    from app import models

    enc_a = np.zeros(128, dtype=np.float32)
    models.add_encoding(db, user_id, "ALICE", enc_a, "ALICE/p1.jpg")

    far = np.full(128, 0.9, dtype=np.float32)
    assert svc.match(db, user_id=user_id, encoding=far, tolerance=0.5) is None


def test_match_without_students_returns_none(app):
    svc = RecognitionService()
    assert svc.match(app.db, user_id=999, encoding=np.zeros(128, np.float32), tolerance=0.5) is None


def test_invalidate_reloads_cache(app, user_id):
    svc = RecognitionService()
    db = app.db

    from app import models

    enc_a = np.zeros(128, dtype=np.float32)
    models.add_encoding(db, user_id, "ALICE", enc_a, "ALICE/p1.jpg")

    assert "ALICE" in svc.get_students(db, user_id)
    # add student after cache was loaded
    enc_b = np.full(128, 0.2, dtype=np.float32)
    models.add_encoding(db, user_id, "BOB", enc_b, "BOB/p1.jpg")
    # stale cache: BOB not present until invalidated
    assert "BOB" not in svc.get_students(db, user_id)
    svc.invalidate(user_id)
    assert "BOB" in svc.get_students(db, user_id)
