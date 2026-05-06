FROM python:3.12-slim

WORKDIR /app

# System deps for PDF processing, OCR & Graphics (Required by PaddleOCR)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    tesseract-ocr \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    wget \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps using requirements.txt for better layer caching
COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --upgrade pip && \
    python3 -m pip install -r requirements.txt flower opencv-python-headless

# Copy the rest of the application
COPY pyproject.toml README.md ./
COPY src/ src/
COPY static/ static/

# Install the project itself in editable mode
RUN python3 -m pip install --no-deps -e .

# Pre-download models for Crawl4AI and PaddleOCR
RUN crawl4ai-download-models || true

# Set env to disable PaddleOCR by default to prevent crashes in unstable environments
ENV DISABLE_PADDLEOCR=True
ENV PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True

# Pre-warm PaddleOCR (Initializes base models) only if not disabled
RUN if [ "$DISABLE_PADDLEOCR" != "True" ]; then \
    python3 -c "from paddleocr import PaddleOCR; PaddleOCR(lang='en')" || true; \
    fi

# Install Playwright, its system dependencies, and browsers
RUN playwright install --with-deps chromium

# Default command
CMD ["uvicorn", "govnotify.main:app", "--host", "0.0.0.0", "--port", "8000"]
