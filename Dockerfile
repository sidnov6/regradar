# RegRadar — single deployable service (API + console).
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# Install deps first for layer caching.
COPY pyproject.toml README.md ./
COPY regradar ./regradar
RUN pip install --upgrade pip && pip install ".[llm,app]"

# Secrets are injected at runtime (never baked into the image):
#   GROQ_API_KEY, GOOGLE_API_KEY  — optional; the router falls back to a mock floor.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn regradar.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
