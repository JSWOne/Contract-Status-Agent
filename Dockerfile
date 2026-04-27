# Playwright's official Python image ships with Chromium + all system deps pre-installed.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

WORKDIR /app

# Install Python dependencies; re-run playwright install so browser version
# matches whatever pip resolves (base image browser stays as fallback).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && playwright install chromium

COPY . .

# Ensure .tmp dir exists at build time (runtime writes will land here)
RUN mkdir -p .tmp

ENV FLASK_PORT=8080
EXPOSE 8080

CMD ["python", "tools/webhook_listener.py"]
