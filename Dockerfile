FROM python:3.12-slim

# Install system dependencies for pdf2image (poppler), LibreOffice for DOCX conversion, and unrar-free for RAR files
# Note: unrar-free is available in standard Debian repos, while unrar requires non-free repos
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice \
    unrar-free \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first to leverage cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port (se puede configurar vía API_PORT)
ARG API_PORT=8000
EXPOSE ${API_PORT}

# Run application (el puerto se configura vía variable de entorno API_PORT)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-8000}"]
