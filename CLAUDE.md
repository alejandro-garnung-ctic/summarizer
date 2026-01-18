# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Summarizer is a multimodal document processing microservice that extracts titles and descriptions from PDFs, DOCX, ZIP archives, XML files, and emails (.eml) using vision-language models. It supports Google Drive and local filesystem sources.

## Build & Run Commands

### Docker (Recommended)
```bash
# Build and run
docker compose up --build

# Run CLI inside container
docker exec -it summarizer python3 -m app.cli gdrive FOLDER_ID
docker exec -it summarizer python3 -m app.cli local /path/to/files
```

### Local Development
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Run API server (port 8567)
python3 -m uvicorn app.main:app --reload

# Run CLI
python3 -m app.cli local /path/to/files
python3 -m app.cli gdrive FOLDER_ID
python3 -m app.cli retry-failed FOLDER_ID
```

### Health Checks
```bash
curl http://localhost:8567/health
curl http://localhost:8567/health/gdrive
curl http://localhost:8567/health/llm
curl http://localhost:8567/health/vllm
```

## Architecture

### Processing Pipeline by File Type

**PDF & DOCX** (Multimodal):
1. Extract first N + last M pages (configurable, default 2 each)
2. Convert pages to JPEG images via pdf2image (PDF) or LibreOffice→pdf2image (DOCX)
3. Send images + prompt to VLLM (vision-language model)
4. Parse JSON response `{title, description}`

**ZIP Archives** (Macro-summarization):
1. Decompress and recursively process all PDF/DOCX files
2. Aggregate all descriptions
3. Send to LLM for collection-level summary
4. Return hierarchical result with children

**XML & EML** (Text-only):
1. Extract text content (XML: recursive text extraction; EML: headers + body)
2. Send to LLM for description
3. Return plain text description

### Key Services

| File | Purpose |
|------|---------|
| `app/main.py` | FastAPI server with endpoints: `/upload`, `/summarize`, `/process-folder` |
| `app/cli.py` | CLI for batch processing (local/gdrive/retry-failed modes) |
| `app/services/processor.py` | Main orchestrator - routes documents to handlers |
| `app/services/vllm.py` | Multimodal LLM service (PDF/DOCX with images) |
| `app/services/llm.py` | Text-only LLM service (ZIP/XML/EML) |
| `app/services/gdrive.py` | Google Drive API integration |
| `app/services/checkpoint.py` | Checkpoint/resume system for batch processing |

### Data Flow
```
Request → processor.py → [pdf.py|docx.py|xml_eml.py] → [vllm.py|llm.py] → Response
```

## Environment Configuration

Key variables in `.env` (see `.env.example`):

| Variable | Purpose |
|----------|---------|
| `MODEL_API_URL` | LLM API endpoint (required) |
| `VLLM_MODEL` | Multimodal model for PDF/DOCX |
| `LLM_MODEL` | Text-only model for ZIP/XML/EML |
| `USE_VLLM_FOR_ALL` | If true, uses VLLM_MODEL for all file types |
| `GOOGLE_DRIVE_CREDENTIALS` | Path to service account JSON |
| `UNATTENDED_MODE` | Enable checkpoint system for resumable processing |

## System Dependencies

- **poppler-utils**: PDF rendering (for pdf2image)
- **LibreOffice**: DOCX to PDF conversion

Both are installed in the Docker image.

## API Endpoints

- `GET /` - Web UI
- `POST /upload` - Direct file upload
- `POST /summarize` - Process documents from any source
- `POST /process-folder` - Batch process Google Drive folder
- `GET /checkpoint/{folder_id}` - Check processing progress
- `GET /docs` - OpenAPI/Swagger documentation
