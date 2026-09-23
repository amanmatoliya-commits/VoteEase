# VoteEase — Upgrade Summary

## Fixed
- **Missing `/register` route** — `register.html` posted to a route that
  didn't exist. Added the full route with validation (empty fields,
  password length, password match, duplicate college ID, race-safe insert).

## Security
- **Secrets no longer hardcoded.** `SECRET_KEY` and `ADMIN_PASS` are now
  read from environment variables, with safe fallbacks for local dev only.
  Set real values in production (see "Deploying" below).
- **CSRF protection added** via `Flask-WTF`'s `CSRFProtect`. Every POST
  form across `login.html`, `register.html`, `vote.html`, and `admin.html`
  now includes a hidden `csrf_token` field.
- **Upload whitelist.** `add_candidate` now rejects any file that isn't
  `.png/.jpg/.jpeg/.gif/.webp`, and a 5MB max upload size is enforced.
  Filenames are also suffixed with a timestamp to avoid overwriting
  existing candidate photos with the same name.
- **Race-condition handling.** Both the voting insert and the admin
  election-creation flow now handle concurrent-write edge cases instead
  of crashing with an unhandled `IntegrityError`.

## New
- **`requirements.txt`** — pin Flask, Flask-WTF, Werkzeug so `pip install
  -r requirements.txt` works out of the box.
- **`tests/test_app.py`** — pytest suite covering registration, login,
  duplicate registration, wrong password, admin auth gate, and the
  one-vote-per-student DB constraint. Uses an isolated temp SQLite file,
  so it never touches your real `database/voting.db`.
- **End Election button now wired up** — the `end_election` form existed
  in `admin.html` but had no matching handler in `app.py`; it's now
  connected (sets `is_active = 0` on the current election).

## Not changed (still worth knowing about)
- Still on SQLite — fine for a class-sized election (dozens of students),
  but if you ever run this for hundreds of concurrent voters, migrate to
  PostgreSQL to avoid `database is locked` errors under write contention.
- No password reset flow for students who forget their seeded password.
- No audit logging of admin actions.

## Deploying the upgrade to PythonAnywhere

1. In your PythonAnywhere **Web** tab, add environment variables (or set
   them in your WSGI config file before the Flask import):
   ```
   SECRET_KEY=<a long random string, e.g. via `python -c "import secrets; print(secrets.token_hex(32))"`>
   ADMIN_PASS=<a strong password, not the old ADMIN0905>
   ```
2. Upload/pull the new files, then in a Bash console on PythonAnywhere:
   ```
   pip install --user -r requirements.txt
   ```
3. Reload the web app from the Web tab.
4. Click through: register a new test account, log in, vote, confirm the
   admin dashboard "End Election" button now works, and confirm uploading
   a `.txt` file as a candidate photo is rejected.

## Pushing to GitHub

From your local clone of the repo:
```bash
git checkout -b security-upgrade
# copy the new/updated files into place, then:
git add app.py requirements.txt tests/ templates/login.html templates/register.html templates/vote.html templates/admin.html CHANGES.md
git commit -m "Add register route, CSRF protection, env-var secrets, upload whitelist, tests"
git push origin security-upgrade
```
Then open a pull request on GitHub from `security-upgrade` into `main` so
you have a clean diff to review before merging.
