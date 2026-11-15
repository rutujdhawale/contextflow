# ContextFlow - Structural Graph-RAG Container
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATHCONTEXT_HYDRADB_URL=http://hydradb:8443 \
    PATHCONTEXT_GRAPH_ID=default \
    PATHCONTEXT_CELL_ID=cell-0

WORKDIR /app

# Install system dependencies (Poppler for PDF text extraction)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Default command launches the interactive ContextFlow TUI console
CMD ["python3", "tui.py"]
