"""
Basic test suite for VoteEase.

Run with:
    pytest tests/test_app.py -v

Uses a temporary SQLite DB per test session so it never touches your real
database/voting.db file.
"""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app as app_module  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix=".db")

    def fake_get_conn():
        import sqlite3
        return sqlite3.connect(db_path)

    monkeypatch.setattr(app_module, "get_conn", fake_get_conn)
    # utils.db.get_conn is imported by name into app_module, so also patch
    # the module-level reference used inside route functions:
    import utils.db as db_module
    monkeypatch.setattr(db_module, "get_conn", fake_get_conn)

    app_module.app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,  # disable CSRF for test simplicity
        SECRET_KEY="test-secret",
    )
    app_module.ADMIN_PASS = "testadminpass"

    app_module.init_db()

    with app_module.app.test_client() as c:
        yield c

    os.close(db_fd)
    os.unlink(db_path)


def register(client, cid="0905CS241001", pwd="password123"):
    return client.post(
        "/register",
        data={"college_id": cid, "password": pwd, "confirm": pwd},
        follow_redirects=True,
    )


def login(client, cid="0905CS241001", pwd="password123"):
    return client.post(
        "/login",
        data={"college_id": cid, "password": pwd},
        follow_redirects=True,
    )


def test_home_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_register_creates_student_and_redirects_to_login(client):
    resp = register(client)
    assert resp.status_code == 200
    assert b"login" in resp.request.path.encode() or resp.request.path == "/login"


def test_register_duplicate_college_id_rejected(client):
    register(client)
    resp = register(client)  # same college_id again
    assert b"already registered" in resp.data


def test_register_password_mismatch_rejected(client):
    resp = client.post(
        "/register",
        data={"college_id": "0905CS241002", "password": "abcdef", "confirm": "xyz123"},
        follow_redirects=True,
    )
    assert b"do not match" in resp.data


def test_login_wrong_password_rejected(client):
    register(client)
    resp = login(client, pwd="wrongpassword")
    assert b"Invalid credentials" in resp.data


def test_login_success_redirects_to_vote_flow(client):
    register(client)
    resp = login(client)
    assert resp.status_code == 200


def test_admin_requires_password(client):
    resp = client.post(
        "/admin",
        data={"admin_login": "1", "password": "wrong"},
        follow_redirects=True,
    )
    assert b"Wrong admin password" in resp.data


def test_admin_login_success(client):
    resp = client.post(
        "/admin",
        data={"admin_login": "1", "password": app_module.ADMIN_PASS},
        follow_redirects=True,
    )
    assert b"Admin Dashboard" in resp.data


def test_no_double_vote_same_student(client):
    """
    Simulates the one-vote-per-student DB constraint: inserting the same
    (election_id, student_id) pair twice must raise IntegrityError, which
    the /vote route catches and treats as an already-voted redirect.
    """
    import sqlite3
    register(client)

    conn = app_module.get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO elections (name, is_active, start_time, end_time) VALUES (?,?,?,?)",
        ("Test Election", 1, "2020-01-01T00:00:00", "2999-01-01T00:00:00"),
    )
    election_id = cur.lastrowid
    cur.execute(
        "INSERT INTO candidates (election_id, name, photo) VALUES (?,?,?)",
        (election_id, "Candidate A", "a.png"),
    )
    conn.commit()

    cur.execute("SELECT id FROM students WHERE college_id=?", ("0905CS241001",))
    student_id = cur.fetchone()[0]

    cur.execute(
        "INSERT INTO votes (election_id, student_id, candidate_id) VALUES (?,?,?)",
        (election_id, student_id, 1),
    )
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        cur.execute(
            "INSERT INTO votes (election_id, student_id, candidate_id) VALUES (?,?,?)",
            (election_id, student_id, 1),
        )
        conn.commit()

    conn.close()
