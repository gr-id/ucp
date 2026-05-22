FROM python:3.11-slim

# uv is the fastest way to install Python deps deterministically.
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install dependencies first for better Docker layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group agent

# Project source.
COPY services/ ./services/
COPY agent/ ./agent/
COPY ui/ ./ui/
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
# Cloud Run injects PORT; default to 8080 for local testing.
ENV PORT=8080
EXPOSE 8080

# Single entrypoint launches both merchant (loopback :8001) and Streamlit ($PORT).
CMD ["/app/entrypoint.sh"]
