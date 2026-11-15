# ContextFlow - Structural Graph-RAG Container
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=7681 \
    PATHCONTEXT_HYDRADB_URL=http://hydradb:8443 \
    PATHCONTEXT_GRAPH_ID=default \
    PATHCONTEXT_CELL_ID=cell-0

WORKDIR /app

# Install system dependencies (Poppler for PDF text extraction, ttyd for web TUI, psmisc for socket mgmt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    ttyd \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure run_web.sh is executable
RUN chmod +x run_web.sh tui.py

EXPOSE 7681 10000

# Default command launches ContextFlow over web terminal on $PORT
CMD ["./run_web.sh"]
