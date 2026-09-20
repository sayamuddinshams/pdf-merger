"""Authentication via Supabase (Backend-as-a-Service).

Identity lives in Supabase: users sign up / log in with email + password, or
with "Continue with Google". This module only manages the session tokens in the
Flask session cookie and exposes the current user to the rest of the app.
"""

import base64
import json
import time
from functools import wraps

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from supabase import Client, create_client

bp = Blueprint("auth", __name__)

# Rate limiter (shared with app.py). In-memory storage is fine for a single
# process; switch to Redis for multi-worker deployments.
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per hour"],
)

_supabase: Client | None = None


def init_supabase(app):
    """Create the Supabase client when credentials are configured."""
    global _supabase
    if app.config.get("SUPABASE_ENABLED"):
        _supabase = create_client(
            app.config["SUPABASE_URL"],
            app.config["SUPABASE_ANON_KEY"],
        )


def get_supabase():
    """The shared Supabase client (None when not configured)."""
    return _supabase


# --------------------------------------------------------------------------
# Session helpers
# --------------------------------------------------------------------------

def _decode_claims(access_token):
    """Decode (without verifying) the JWT payload to read its expiry."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception:
        return {}


def _initials(name):
    parts = str(name or "").split()
    first = parts[0][0] if parts else "?"
    last = parts[-1][0] if len(parts) > 1 else ""
    return (first + last).upper()


def _store_session(res):
    """Persist a Supabase auth response (.session + .user) in the Flask session."""
    if not res or not getattr(res, "session", None):
        return None

    token = res.session
    sb_user = getattr(res, "user", None)
    meta = (sb_user.user_metadata or {}) if sb_user else {}

    email = (sb_user.email if sb_user else None) or ""
    name = (
        meta.get("name")
        or meta.get("full_name")
        or (email.split("@")[0] if email else "User")
    )
    avatar = meta.get("avatar_url") or meta.get("picture") or meta.get("avatar")

    payload = {
        "access_token": token.access_token,
        "refresh_token": token.refresh_token,
        "exp": _decode_claims(token.access_token).get("exp"),
        "user": {
            "id": sb_user.id if sb_user else None,
            "email": email or None,
            "name": name,
            "avatar": avatar or None,
            "initials": _initials(name),
        },
    }
    session["supabase_session"] = payload
    return payload


def _refresh_session():
    """Try to refresh the stored tokens; returns the new payload or None."""
    data = session.get("supabase_session")
    if not data:
        return None
    try:
        supabase = get_supabase()
        supabase.auth.set_session(data["access_token"], data["refresh_token"])
        res = supabase.auth.refresh_session()
        return _store_session(res)
    except Exception:
        session.pop("supabase_session", None)
        return None


def get_current_user():
    """Return the current user dict (id/email/name/avatar/initials) or None."""
    data = session.get("supabase_session")
    if not data:
        return None
    if data.get("exp") and time.time() > data["exp"] - 30:
        data = _refresh_session()
        if not data:
            return None
    return data["user"]


def require_login(fn):
    """Require an authenticated user; reply 401 JSON for API calls."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if get_current_user() is None:
            return jsonify({"ok": False, "error": "Please log in to merge your PDFs."}), 401
        return fn(*args, **kwargs)

    return wrapper


def _supabase_message(exc):
    """Pull a readable message out of a supabase/gotrue error."""
    return (
        getattr(exc, "message", None)
        or str(exc).strip()
        or "Something went wrong. Please try again."
    )


def _supabase_ready():
    return bool(current_app.config.get("SUPABASE_ENABLED") and get_supabase())


# --------------------------------------------------------------------------
# Email / password
# --------------------------------------------------------------------------

@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if get_current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please fill in both fields.", "error")
        elif not _supabase_ready():
            flash(
                "Supabase isn't configured yet — add SUPABASE_URL and SUPABASE_ANON_KEY to .env.",
                "error",
            )
        else:
            try:
                res = get_supabase().auth.sign_in_with_password(
                    {"email": email, "password": password}
                )
                payload = _store_session(res)
                session["just_signed_in"] = True
                flash(f"Welcome back, {payload['user']['name']}!", "success")
                return redirect(url_for("index"))
            except Exception as exc:
                flash(_supabase_message(exc), "error")

    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
@limiter.limit("5 per minute", methods=["POST"])
def signup():
    if get_current_user():
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        name = request.form.get("name", "").strip()
        display_name = name or email.split("@")[0]

        if not email or "@" not in email:
            flash("Please enter a valid email address.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
        elif not _supabase_ready():
            flash(
                "Supabase isn't configured yet — add SUPABASE_URL and SUPABASE_ANON_KEY to .env.",
                "error",
            )
        else:
            try:
                res = get_supabase().auth.sign_up(
                    {
                        "email": email,
                        "password": password,
                        "options": {"data": {"name": display_name}},
                    }
                )
                if res.session:
                    _store_session(res)
                    session["just_signed_in"] = True
                    flash(f"Account created — welcome, {display_name}!", "success")
                    return redirect(url_for("index"))
                # Email confirmation required — no session yet.
                flash(
                    "Account created! Check your email to confirm your address, then log in.",
                    "success",
                )
                return redirect(url_for("auth.login"))
            except Exception as exc:
                flash(_supabase_message(exc), "error")

    return render_template("signup.html")


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    data = session.pop("supabase_session", None)
    if data and get_supabase():
        try:
            get_supabase().auth.set_session(data["access_token"], data["refresh_token"])
            get_supabase().auth.sign_out()
        except Exception:
            pass  # local logout still applies
    flash("You've been logged out.", "success")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------
# Google ("Continue with Google")
# --------------------------------------------------------------------------

@bp.route("/login/google")
def google_login():
    if not _supabase_ready():
        flash(
            "Supabase isn't configured yet — add SUPABASE_URL and SUPABASE_ANON_KEY to .env.",
            "error",
        )
        return redirect(url_for("auth.login"))

    redirect_to = (
        current_app.config["SITE_URL"] + url_for("auth.callback")
    )
    try:
        res = get_supabase().auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {
                    "redirect_to": redirect_to,
                    # Always show Google's account chooser so the user can pick
                    # (or switch) which Google account signs in each time.
                    "query_params": {"prompt": "select_account"},
                },
            }
        )
        target = getattr(res, "url", None) or (res if isinstance(res, str) else None)
        if not target:
            flash("Couldn't reach Google sign-in — please try again.", "error")
            return redirect(url_for("auth.login"))
        return redirect(target)
    except Exception as exc:
        flash(_supabase_message(exc), "error")
        return redirect(url_for("auth.login"))


@bp.route("/auth/callback")
def callback():
    """Supabase redirects here after a Google login, with ?code=..."""
    code = request.args.get("code")
    if not code or not _supabase_ready():
        flash("Google sign-in didn't include an authorization code.", "error")
        return redirect(url_for("auth.login"))

    # PKCE exchange: pass a params dict (the library supplies the code_verifier
    # that sign_in_with_oauth stored when it built the authorize URL).
    try:
        res = get_supabase().auth.exchange_code_for_session(
            {
                "auth_code": code,
                "redirect_to": current_app.config["SITE_URL"]
                + url_for("auth.callback"),
            }
        )
        payload = _store_session(res)
        session["just_signed_in"] = True
        flash(f"Signed in with Google — welcome, {payload['user']['name']}!", "success")
        return redirect(url_for("index"))
    except Exception as exc:
        flash(_supabase_message(exc), "error")
        return redirect(url_for("auth.login"))