FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV=production

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Bind to $PORT when Render (or any orchestrator) sets it, defaulting to 8000
# for plain `docker run -p 8000:8000`. Shell form so ${PORT} expands.
CMD gunicorn -w 1 -b 0.0.0.0:${PORT:-8000} --timeout 120 wsgi:application