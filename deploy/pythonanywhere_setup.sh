#!/usr/bin/env bash
# ============================================================
# PDF Weave — one-shot setup for PythonAnywhere (free plan)
# ------------------------------------------------------------
# Run from a PythonAnywhere Bash console, AFTER cloning the repo:
#   git clone git@github.com:sayamuddinshams/pdf-merger.git
#   cd pdf-merger && bash deploy/pythonanywhere_setup.sh
# ============================================================
set -euo pipefail

APP_DIR="$HOME/pdf-merger"
if [ ! -f "$APP_DIR/app.py" ]; then
  echo "ERROR: $APP_DIR/app.py not found. Clone the repo first." >&2
  exit 1
fi

cd "$APP_DIR"
echo "==> Creating Python virtualenv + installing requirements"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo "==> Ensuring production env file exists (fill it in next)"
if [ ! -f .env.production ]; then
  cp .env.production.example .env.production
fi

USERNAME="$(whoami)"
SITE_URL="https://${USERNAME}.pythonanywhere.com"
WSGI_FILE="/var/www/${USERNAME}_pythonanywhere_com_wsgi.py"

echo "==> Writing WSGI config -> $WSGI_FILE"
cat > "$WSGI_FILE" <<EOF
import os, sys

project_home = u'$APP_DIR'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Load .env.production (gitignored; edit it with the real values)
os.environ['ENV_FILE'] = '$APP_DIR/.env.production'
os.environ.setdefault('ENV', 'production')

from wsgi import application  # noqa: E402
EOF

mkdir -p "$APP_DIR/uploads/merged"

echo ""
echo "============================================================"
echo " Done! Manual steps remaining (PythonAnywhere UI):"
echo "============================================================"
echo " 1. Files tab -> edit  ~/pdf-merger/.env.production :"
echo "      SECRET_KEY         = <64-char random, from your PC's .env.production>"
echo "      ENV                = production"
echo "      SITE_URL           = $SITE_URL"
echo "      SUPABASE_URL       = https://umhgymrljxztearsvfsr.supabase.co"
echo "      SUPABASE_ANON_KEY  = <anon key from your PC's .env>"
echo ""
echo " 2. Web tab -> 'Add a new web app' -> Manual configuration"
echo "      - Python: the newest offered (3.12+)"
echo "      - Virtualenv field: $APP_DIR/venv"
echo "      - WSGI config file is already at: $WSGI_FILE"
echo "      - Static files:  URL /static/  ->  Directory $APP_DIR/static"
echo ""
echo " 3. Web tab -> click Reload, then open:"
echo "      $SITE_URL/api/health"
echo ""
echo " 4. Supabase -> Authentication -> URL Configuration ->"
echo "    Redirect URLs -> add  $SITE_URL/**"
echo "============================================================"