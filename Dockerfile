# syntax=docker/dockerfile:1

# ── Stage 1: build the React frontend ────────────────────────────────────────
FROM node:20-slim AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend with Chrome ──────────────────────────────────────
FROM python:3.11-slim

# Install Chrome and its dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget gnupg2 ca-certificates curl unzip \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub \
       | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
             http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    # Install ChromeDriver matching installed Chrome version
    && CHROME_MAJOR=$(google-chrome --version | grep -oP '\d+' | head -1) \
    && CHROMEDRIVER_VERSION=$(curl -fsSL \
         "https://googlechromelabs.github.io/chrome-for-testing/LATEST_RELEASE_${CHROME_MAJOR}") \
    && curl -fsSL \
         "https://storage.googleapis.com/chrome-for-testing-public/${CHROMEDRIVER_VERSION}/linux64/chromedriver-linux64.zip" \
         -o /tmp/chromedriver.zip \
    && unzip -q /tmp/chromedriver.zip -d /tmp/ \
    && mv /tmp/chromedriver-linux64/chromedriver /usr/local/bin/chromedriver \
    && chmod +x /usr/local/bin/chromedriver \
    && rm -rf /tmp/chromedriver* /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source and built frontend
COPY backend/ ./backend/
COPY --from=frontend-builder /app/frontend/dist ./frontend/dist

ENV PORT=8000
EXPOSE 8000

WORKDIR /app/backend

# Single worker + threads so Chrome doesn't spawn out of control;
# timeout 900 s covers the longest storefronts (100+ videos).
CMD ["gunicorn", \
     "--workers", "1", \
     "--threads", "4", \
     "--timeout", "900", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "-", \
     "--log-level", "info", \
     "api:app"]
