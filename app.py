"""
PDF Weave — Flask backend (production build).

Identity is handled by Supabase (Backend-as-a-Service): email/password sign-up
and login, plus "Continue with Google". See .env.example and README.

Routes
  GET  /                    -> UI (dark-mode, responsive)
  GET  /api/health          -> health check (load balancers / tunnels)
  POST /api/merge           -> merge PDFs with per-file page ranges (login required)
  GET  /api/me              -> small JSON describing the current session
  /login  /signup  /logout  -> email/password authentication via Supabase
  /login/google             -> "Continue with Google" (Supabase-hosted OAuth)
  /auth/callback            -> Supabase OAuth callback

Run (development)
  python app.py                        -> http://127.0.0.1:5001

Run (production, Windows friendly)
  python serve.py                      -> Waitress on 0.0.0.0:5001

Run (production, Linux / Docker)
  gunicorn -w 2 -b 0.0.0.0:8000 wsgi:application

Deploy behind Cloudflare with a free `cloudflared` tunnel — see README.
"""

import io
import logging
import logging.handlers
import os
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlparse

from dotenv import load_dotenv
from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError
from pypdf import PdfReader, PdfWriter
from werkzeug.middleware.proxy_fix import ProxyFix

from auth import (
    bp as auth_bp,
    get_current_user,
    init_supabase,
    limiter,
    require_login,
)

load_dotenv(os.getenv("ENV_FILE") or ".env")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

SITE_URL = os.getenv("SITE_URL", "http://127.0.0.1:5001").rstrip("/")
ENV = os.getenv("ENV", "development").lower()
DEBUG = os.getenv("DEBUG", "").lower() in {"1", "true", "yes"}
DEV_SECRET = "dev-secret-change-me-in-prod"

app = Flask(__name__)
app.config.update(
    ENV=ENV,
    DEBUG=DEBUG,
    SECRET_KEY=os.getenv("SECRET_KEY", DEV_SECRET),
    SITE_URL=SITE_URL,
    MAX_CONTENT_LENGTH=50 * 1024 * 1024,  # 50 MB request body
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # Secure cookies only when served over HTTPS (e.g. the Cloudflare tunnel).
    SESSION_COOKIE_SECURE=SITE_URL.startswith("https://"),
    SUPABASE_URL=os.getenv("SUPABASE_URL", "").strip(),
    SUPABASE_ANON_KEY=os.getenv("SUPABASE_ANON_KEY", "").strip(),
    SUPABASE_ENABLED=bool(
        os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_ANON_KEY")
    ),
)

# Merged PDFs are stored for a short time so the thank-you page can show a
# preview, then cleaned up automatically (30-minute TTL, cleanup once a minute).
MERGED_DIR = os.path.join(BASE_DIR, "uploads", "merged")
MERGE_TTL_SECONDS = 30 * 60
_last_cleanup = 0.0

if ENV == "production":
    if app.config["SECRET_KEY"] == DEV_SECRET:
        raise RuntimeError(
            "SECRET_KEY must be set in production (see .env.production.example)."
        )
    if not SITE_URL.startswith("https://"):
        raise RuntimeError("SITE_URL must be an https:// URL in production.")

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("pdfweave")
log.setLevel(logging.INFO if ENV == "production" else logging.DEBUG)

log_file = os.getenv("LOG_FILE", "").strip()
if log_file:
    os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)

# --------------------------------------------------------------------------
# Middleware / extensions
# --------------------------------------------------------------------------

# Trust X-Forwarded-* headers coming from Cloudflare / nginx.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

csrf = CSRFProtect(app)
limiter.init_app(app)

init_supabase(app)
app.register_blueprint(auth_bp)


@app.before_request
def _make_session_permanent():
    session.permanent = True


@app.context_processor
def inject_globals():
    """Make the session's user and config flags available to every template."""
    return {
        "supabase_enabled": app.config["SUPABASE_ENABLED"],
        "current_user": get_current_user(),
    }


# --------------------------------------------------------------------------
# Security headers
# --------------------------------------------------------------------------

@app.after_request
def _security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

    supabase_host = ""
    if app.config["SUPABASE_ENABLED"]:
        supabase_host = urlparse(app.config["SUPABASE_URL"]).netloc

    if request.path.startswith("/preview/"):
        # The preview PDF is embedded in an <iframe> on the same-origin
        # thank-you page, so it needs frame-ancestors 'self' (not 'none').
        resp.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
    else:
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            f"connect-src 'self' https://{supabase_host}; "
            "frame-ancestors 'none'; "
            "form-action 'self'"
        )

    if app.config["SITE_URL"].startswith("https://"):
        resp.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return resp


# --------------------------------------------------------------------------
# Error handlers
# --------------------------------------------------------------------------

def _is_api():
    return request.path.startswith("/api/")


@app.errorhandler(CSRFError)
def _csrf_error(e):
    if _is_api():
        return jsonify({"ok": False, "error": "Session expired — refresh the page and try again."}), 400
    return render_template("error.html", code=400, message="Session expired — go back and try again."), 400


@app.errorhandler(404)
def _not_found(e):
    if _is_api():
        return jsonify({"ok": False, "error": "Not found."}), 404
    return render_template("error.html", code=404, message="That page doesn't exist."), 404


@app.errorhandler(413)
def _too_large(e):
    if _is_api():
        return jsonify({"ok": False, "error": "Upload is too large (50 MB limit)."}), 413
    return render_template("error.html", code=413, message="Upload is too large (50 MB limit)."), 413


@app.errorhandler(500)
def _server_error(e):
    log.exception("Unhandled error: %s", e)
    if _is_api():
        return jsonify({"ok": False, "error": "Internal server error."}), 500
    return render_template("error.html", code=500, message="Something went wrong on our side."), 500


# --------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the PDF merger UI."""
    # One-shot flag: flickers a "welcome back" toast right after sign-in.
    just_signed_in = bool(session.pop("just_signed_in", False))
    return render_template("index.html", just_signed_in=just_signed_in)


@app.route("/about")
def about():
    """About PDF Weave."""
    return render_template("about.html")


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

@app.route("/api/health")
def api_health():
    """Health check for load balancers and Cloudflare."""
    return jsonify({"ok": True, "service": "pdfweave"})


@app.route("/api/me")
def api_me():
    """Small JSON endpoint so the frontend knows who's signed in."""
    user = get_current_user()
    return jsonify(
        {
            "authenticated": bool(user),
            "user": user,
        }
    )


# --------------------------------------------------------------------------
# Merge engine
# --------------------------------------------------------------------------

_PAGE_PART = re.compile(r"^\s*(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse_page_spec(spec, total):
    """Turn a page-range string into a list of 1-based page numbers.

    Accepts "", "all", "2-5", "1,3,8", "2-5,8", "10-12".
    Out-of-range pages are clamped (a range may safely extend past the end);
    an empty result raises ValueError.
    """
    spec = (spec or "").strip().lower()
    if not spec or spec == "all":
        return list(range(1, total + 1))

    pages = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        m = _PAGE_PART.fullmatch(part)
        if not m:
            raise ValueError(f"'{part}' isn't a valid page range (try e.g. 2-5 or 1,3,8).")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start > end:
            raise ValueError(f"'{part}' has the start page after the end page.")
        pages.extend(range(start, min(end, total) + 1))

    pages = [p for p in pages if 1 <= p <= total]
    if not pages:
        raise ValueError(f"No valid pages in '{spec}' (this file has {total} page{'s' if total != 1 else ''}).")
    return pages


@app.route("/api/merge", methods=["POST"])
@require_login
def merge_pdfs():
    """Merge uploaded PDFs, optionally taking page ranges per file.

    Multipart request:
      files[i]  -> the PDF file
      pages[i]  -> its page range ("", "all", "2-5", "1,3") — parallel arrays

    Response: the merged PDF as an attachment (application/pdf),
    or JSON {"ok": false, "error": "..."} on failure.
    """
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files received."}), 400
    if len(files) < 2:
        return jsonify({"ok": False, "error": "Please upload at least two PDFs to merge."}), 400

    specs = request.form.getlist("pages")
    specs = (specs + ["all"] * len(files))[: len(files)]

    writer = PdfWriter()
    try:
        for idx, upload in enumerate(files):
            try:
                reader = PdfReader(upload.stream)
            except Exception:
                log.warning("Could not read PDF %r", upload.filename)
                return jsonify(
                    {"ok": False, "error": f"'{upload.filename}' isn't a readable PDF."}
                ), 400

            total = len(reader.pages)
            if total == 0:
                return jsonify(
                    {"ok": False, "error": f"'{upload.filename}' has no pages."}
                ), 400

            pages = parse_page_spec(specs[idx], total)
            for p in pages:
                writer.add_page(reader.pages[p - 1])
    except ValueError as exc:
        log.info("Merge rejected: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        log.exception("Merge failed: %s", exc)
        return jsonify({"ok": False, "error": "Couldn't merge these files — please try again."}), 500

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    log.info(
        "User %s merged %d file(s) into %d page(s)",
        getattr(get_current_user(), "get", lambda: None)("email") or "?",
        len(files),
        len(writer.pages),
    )

    # Store the merged PDF under a random token so the user can preview and
    # download it from the thank-you page. Old files are cleaned up on a TTL.
    os.makedirs(MERGED_DIR, exist_ok=True)
    _cleanup_old_merges()

    token = secrets.token_urlsafe(24)
    merged_path = os.path.join(MERGED_DIR, token + ".pdf")
    with open(merged_path, "wb") as fh:
        fh.write(output.getvalue())

    return jsonify(
        {
            "ok": True,
            "token": token,
            "pageCount": len(writer.pages),
            "thankyouUrl": url_for("thankyou", token=token),
            "downloadUrl": url_for("download_merge", token=token),
        }
    )


# --------------------------------------------------------------------------
# Thank-you page / preview / download
# --------------------------------------------------------------------------

def _require_user_or_redirect():
    """Redirect anonymous visitors to the login page (HTML flow)."""
    if get_current_user() is None:
        return redirect(url_for("auth.login"))
    return None


def _merge_file(token):
    """Return the file path for a valid merge token, or None."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,80}", token or ""):
        return None
    path = os.path.join(MERGED_DIR, token + ".pdf")
    return path if os.path.isfile(path) else None


def _cleanup_old_merges():
    """Remove merged PDFs older than the TTL (at most once per minute)."""
    global _last_cleanup
    now = time.time()
    if now - _last_cleanup < 60:
        return
    _last_cleanup = now
    cutoff = now - MERGE_TTL_SECONDS
    try:
        for name in os.listdir(MERGED_DIR):
            path = os.path.join(MERGED_DIR, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.remove(path)
                    log.info("Cleaned up expired merge: %s", name)
            except OSError:
                pass
    except OSError:
        pass


def _merge_not_found():
    return (
        render_template(
            "error.html",
            code=404,
            message="That merged file has expired or wasn't found.",
        ),
        404,
    )


@app.route("/thankyou/<token>")
def thankyou(token):
    """Thank-you page: shows the merged PDF preview and a download button."""
    guard = _require_user_or_redirect()
    if guard:
        return guard
    if not _merge_file(token):
        return _merge_not_found()
    _cleanup_old_merges()
    return render_template(
        "thankyou.html",
        token=token,
        preview_url=url_for("preview_merge", token=token),
        download_url=url_for("download_merge", token=token),
    )


@app.route("/preview/<token>")
def preview_merge(token):
    """Stream the merged PDF inline so the thank-you page can embed it."""
    guard = _require_user_or_redirect()
    if guard:
        return guard
    path = _merge_file(token)
    if not path:
        return _merge_not_found()
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=False,
        conditional=True,
    )


@app.route("/download/<token>")
def download_merge(token):
    """Download the merged PDF as an attachment (saves to the user's machine)."""
    guard = _require_user_or_redirect()
    if guard:
        return guard
    path = _merge_file(token)
    if not path:
        return _merge_not_found()
    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="merged.pdf",
    )


if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5001,
        debug=app.config["DEBUG"],
    )