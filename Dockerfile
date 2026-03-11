FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by Pillow for font/image support
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev \
    libjpeg62-turbo-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run as non-root user for security
RUN useradd --create-home appuser && \
    mkdir -p /app/outputs && chown -R appuser:appuser /app/outputs
USER appuser

EXPOSE 8000

# Default: serve the web UI
CMD ["python", "app.py"]
