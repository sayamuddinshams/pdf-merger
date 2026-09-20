"""Production server for Windows (Waitress).

Run:  python serve.py
Env:  PORT  (default 5001)
"""

import os

from waitress import serve

from app import app

PORT = int(os.getenv("PORT", "5001"))

if __name__ == "__main__":
    print(f"MergePDF serving on 0.0.0.0:{PORT} via Waitress")
    serve(app, host="0.0.0.0", port=PORT, threads=8)