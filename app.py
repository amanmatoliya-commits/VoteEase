from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_wtf import CSRFProtect
from utils.db import get_conn
from utils.security import hash_password, verify_password
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
import sqlite3, os

app = Flask(__name__)

# ---------------- SECRETS (env-var backed, no hardcoding) ----------------
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24)
ADMIN_PASS = os.environ.get("ADMIN_PASS")  # override this in production!

# ---------------- CSRF ----------------
csrf = CSRFProtect(app)

# ---------------- CONFIG ----------------
UPLOAD_FOLDER = "static/photos"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB upload cap


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# ---------------- HELPERS ----------------
def row_to_dict(row):
    return dict(row) if row else None


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def expire_elections():
    conn = get_conn()
    cur = conn.cursor()
    now = datetime.now().isoformat()
    cur.execute(
        "UPDATE elections SET is_active=0 WHERE is_active=1 AND end_time < ?",
        (now,)
    )
    conn.commit()
    conn.close()


# ---------------- NO CACHE ----------------
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-store"
    return response


# ---------------- LOGOUT ----------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------- DB INIT ----------------
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY,
        college_id TEXT UNIQUE,
        password_hash TEXT
    );

    CREATE TABLE IF NOT EXISTS elections (
        id INTEGER PRIMARY KEY,
        name TEXT,
        is_active INTEGER DEFAULT 1,
        start_time TEXT,
        end_time TEXT
    );

    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY,
        election_id INTEGER,
        name TEXT,
        photo TEXT
    );

    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY,
        election_id INTEGER,
        student_id INTEGER,
        candidate_id INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(election_id, student_id)
    );
    """)
    conn.commit()
    conn.close()


def seed_students():
    conn = get_conn()
    cur = conn.cursor()
    for i in range(1, 65):
        cid = f"0905CS241{str(i).zfill(3)}"
        cur.execute(
            "INSERT OR IGNORE INTO students (college_id,password_hash) VALUES (?,?)",
            (cid, hash_password(f"{cid}#"))
        )
    conn.commit()
    conn.close()


# ---------------- HOME ----------------
@app.route("/")
@app.route("/home")
def home():
    expire_elections()
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM elections WHERE is_active=1")
    active_elections = [dict(r) for r in cur.fetchall()]
    conn.close()
    for e in active_elections:
        e["status"] = "Active"
    return render_template("home.html", active_elections=active_elections)


# ---------------- REGISTER ----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        cid = request.form.get("college_id", "").strip()
        pwd = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not cid or not pwd:
            flash("All fields are required", "danger")
            return redirect(url_for("register"))

        if pwd != confirm:
            flash("Passwords do not match", "danger")
            return redirect(url_for("register"))

        if len(pwd) < 6:
            flash("Password must be at least 6 characters", "danger")
            return redirect(url_for("register"))

        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM students WHERE college_id=?", (cid,))
        if cur.fetchone():
            flash("College ID already registered", "danger")
            conn.close()
            return redirect(url_for("register"))

        try:
            cur.execute(
                "INSERT INTO students (college_id, password_hash) VALUES (?,?)",
                (cid, hash_password(pwd))
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("College ID already registered", "danger")
            conn.close()
            return redirect(url_for("register"))

        conn.close()
        flash("Registration successful. Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


# ---------------- LOGIN ----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        cid = request.form["college_id"]
        pwd = request.form["password"]

        conn = get_conn()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM students WHERE college_id=?", (cid,))
        student = row_to_dict(cur.fetchone())
        conn.close()

        if not student or not verify_password(student["password_hash"], pwd):
            flash("Invalid credentials", "danger")
            return redirect(url_for("login"))

        session.clear()
        session["student"] = {"id": student["id"], "college_id": cid}
        return redirect(url_for("vote"))

    return render_template("login.html")


# ---------------- VOTE ----------------
@app.route("/vote", methods=["GET", "POST"])
def vote():
    if "student" not in session:
        return redirect(url_for("login"))

    expire_elections()

    sid = session["student"]["id"]
    now = datetime.now().isoformat()

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT * FROM elections
        WHERE is_active=1 AND start_time<=? AND end_time>=?
        LIMIT 1
    """, (now, now))
    election = row_to_dict(cur.fetchone())

    if not election:
        conn.close()
        return render_template("election.html")

    cur.execute(
        "SELECT 1 FROM votes WHERE election_id=? AND student_id=?",
        (election["id"], sid)
    )
    has_voted = cur.fetchone() is not None

    if request.method == "POST":
        if has_voted:
            conn.close()
            return redirect(url_for("thanks"))

        candidate_id = request.form.get("candidate")
        if not candidate_id:
            conn.close()
            flash("Please select a candidate", "danger")
            return redirect(url_for("vote"))

        try:
            cur.execute(
                "INSERT INTO votes (election_id,student_id,candidate_id) VALUES (?,?,?)",
                (election["id"], sid, candidate_id)
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # Race condition: another request already recorded this student's vote.
            conn.close()
            return redirect(url_for("thanks"))

        conn.close()
        return redirect(url_for("thanks"))

    cur.execute("SELECT * FROM candidates WHERE election_id=?", (election["id"],))
    candidates = rows_to_dicts(cur.fetchall())
    conn.close()

    return render_template(
        "vote.html",
        election=election,
        candidates=candidates,
        has_voted=has_voted,
        end_time=election["end_time"]
    )


# ---------------- THANKS ----------------
@app.route("/thanks")
def thanks():
    return render_template("thanks.html")


# ---------------- RESULTS ----------------
@app.route("/results")
def results():
    expire_elections()

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM elections ORDER BY id DESC LIMIT 1")
    election = row_to_dict(cur.fetchone())

    if not election:
        conn.close()
        return render_template("results.html", status="no_election")

    if election["is_active"] == 1:
        conn.close()
        return render_template("results.html", status="running", election=election)

    cur.execute("""
        SELECT c.name, c.photo, COUNT(v.id) AS votes
        FROM candidates c
        LEFT JOIN votes v ON c.id=v.candidate_id
        WHERE c.election_id=?
        GROUP BY c.id
        ORDER BY votes DESC
    """, (election["id"],))

    results = rows_to_dicts(cur.fetchall())
    conn.close()

    return render_template(
        "results.html",
        status="ended",
        election=election,
        results=results,
        winner=results[0] if results else None
    )


# ---------------- ADMIN ----------------
@app.route("/admin", methods=["GET", "POST"])
def admin():
    if request.method == "POST" and "admin_login" in request.form:
        if request.form["password"] == ADMIN_PASS:
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Wrong admin password", "danger")

    if "admin" not in session:
        return render_template("admin.html", logged_in=False)

    expire_elections()

    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if request.method == "POST" and "create_election" in request.form:
        try:
            duration = int(request.form["duration"])
        except (ValueError, KeyError):
            flash("Duration must be a number", "danger")
            duration = None

        if duration and duration > 0:
            start = datetime.now()
            end = start + timedelta(minutes=duration)

            cur.execute("UPDATE elections SET is_active=0")
            cur.execute(
                "INSERT INTO elections (name,is_active,start_time,end_time) VALUES (?,?,?,?)",
                (request.form["election_name"], 1, start.isoformat(), end.isoformat())
            )
            conn.commit()

    if request.method == "POST" and "add_candidate" in request.form:
        cur.execute("SELECT id FROM elections WHERE is_active=1 LIMIT 1")
        e = cur.fetchone()
        if e:
            photo = request.files.get("photo")
            if not photo or photo.filename == "":
                flash("Please choose a photo", "danger")
            elif not allowed_file(photo.filename):
                flash("Invalid image file type", "danger")
            else:
                filename = secure_filename(photo.filename)
                # avoid collisions overwriting existing candidate photos
                base, ext = os.path.splitext(filename)
                candidate_name = request.form.get("candidate_name", "").strip()
                if not candidate_name:
                    flash("Candidate name is required", "danger")
                else:
                    unique_name = f"{base}_{int(datetime.now().timestamp())}{ext}"
                    photo.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_name))
                    cur.execute(
                        "INSERT INTO candidates (election_id,name,photo) VALUES (?,?,?)",
                        (e["id"], candidate_name, unique_name)
                    )
                    conn.commit()

    if request.method == "POST" and "end_election" in request.form:
        cur.execute("UPDATE elections SET is_active=0 WHERE is_active=1")
        conn.commit()

    cur.execute("SELECT * FROM elections WHERE is_active=1 LIMIT 1")
    election = row_to_dict(cur.fetchone())

    cur.execute("SELECT COUNT(*) FROM students")
    total_students = cur.fetchone()[0]

    votes_cast = 0
    candidates = []
    students = []

    if election:
        cur.execute("SELECT COUNT(*) FROM votes WHERE election_id=?", (election["id"],))
        votes_cast = cur.fetchone()[0]

        cur.execute("""
            SELECT c.id,c.name,c.photo,COUNT(v.id) AS votes
            FROM candidates c
            LEFT JOIN votes v ON c.id=v.candidate_id
            WHERE c.election_id=?
            GROUP BY c.id
            ORDER BY votes DESC
        """, (election["id"],))
        candidates = rows_to_dicts(cur.fetchall())

        cur.execute("""
            SELECT s.college_id,
                   CASE WHEN v.id IS NOT NULL THEN 1 ELSE 0 END AS has_voted
            FROM students s
            LEFT JOIN votes v
              ON s.id = v.student_id AND v.election_id = ?
            ORDER BY s.college_id
        """, (election["id"],))
        students = rows_to_dicts(cur.fetchall())

    conn.close()

    return render_template(
        "admin.html",
        logged_in=True,
        election=election,
        candidates=candidates,
        students=students,
        total_students=total_students,
        votes_cast=votes_cast,
        votes_remaining=total_students - votes_cast,
        leader=candidates[0] if candidates else None
    )


# ---------------- DELETE CANDIDATE ----------------
@app.route("/delete_candidate/<int:cid>", methods=["POST"])
def delete_candidate(cid):
    if "admin" not in session:
        return redirect(url_for("admin"))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM votes WHERE candidate_id=?", (cid,))
    cur.execute("DELETE FROM candidates WHERE id=?", (cid,))
    conn.commit()
    conn.close()

    flash("Candidate deleted", "success")
    return redirect(url_for("admin"))


# ---------------- DELETE STUDENT ----------------
@app.route("/delete_student/<college_id>", methods=["POST"])
def delete_student(college_id):
    if "admin" not in session:
        return redirect(url_for("admin"))

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM students WHERE college_id=?", (college_id,))
    row = cur.fetchone()

    if row:
        cur.execute("DELETE FROM votes WHERE student_id=?", (row[0],))
        cur.execute("DELETE FROM students WHERE id=?", (row[0],))
        conn.commit()
        flash(f"Student {college_id} deleted", "success")

    conn.close()
    return redirect(url_for("admin"))



@app.route("/robots.txt")
def robots_txt():
    content = """User-agent: *
Allow: /

Sitemap: https://aman5.pythonanywhere.com/sitemap.xml
"""
    return app.response_class(content, mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap_xml():
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://aman5.pythonanywhere.com/</loc>
    </url>
</urlset>
"""
    return app.response_class(content, mimetype="application/xml")



@app.route("/googlec246928b39a849e4.html")
def google_verification():
    return "google-site-verification: googlec246928b39a849e4.html"





# ---------------- RUN ----------------
if __name__ == "__main__":
    init_db()
    seed_students()
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode)
