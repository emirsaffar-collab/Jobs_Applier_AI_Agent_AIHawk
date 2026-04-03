# -----------------------------------------------------------------------
# AIHawk Jobs Applier – Dockerfile
#
# Multi-stage build:
#   1. builder  – install Python dependencies
#   2. runtime  – lean image with Chrome + the application
#
# Build:
#   docker build -t aihawk .
#
# Run (web server):
#   docker run -p 8000:8000 \
#     -e CELERY_BROKER_URL=redis://redis:6379/0 \
#     -e CELERY_RESULT_BACKEND=redis://redis:6379/1 \
#     aihawk
#
# Run (CLI):
#   docker run --rm -it \
#     -v $(pwd)/data_folder:/app/data_folder \
#     aihawk python entrypoint.py
# -----------------------------------------------------------------------

# -----------------------------------------------------------------------
# Stage 1 – dependency builder
# -----------------------------------------------------------------------
FROM python:3.13-slim AS builder

WORKDIR /build

# System build deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# -----------------------------------------------------------------------
# Stage 2 – runtime
# -----------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# Install Chrome + ChromeDriver for PDF generation via Selenium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    xdg-utils \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
       > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

WORKDIR /app

# Copy application source
COPY . .

# Create required directories
RUN mkdir -p data_folder/output log

# Non-root user for security
RUN useradd -m -u 1000 aihawk \
 && chown -R aihawk:aihawk /app
USER aihawk

# Environment defaults (override at runtime)
ENV HOST=0.0.0.0 \
    PORT=8000 \
    LOG_LEVEL=INFO \
    LOG_TO_CONSOLE=true \
    LOG_TO_FILE=true \
    DATABASE_URL=sqlite:///./aihawk.db \
    CELERY_BROKER_URL=memory:// \
    CELERY_RESULT_BACKEND=db+sqlite:///./celery_results.db

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD wget -qO- http://localhost:${PORT}/api/health || exit 1

# Default command: start the web server
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--log-level", "info"]
