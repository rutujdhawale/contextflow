# ContextFlow - Structural Graph-RAG Container
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=10000 \
    PATHCONTEXT_HYDRADB_URL=http://hydradb:8443 \
    PATHCONTEXT_GRAPH_ID=default \
    PATHCONTEXT_CELL_ID=cell-0

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    curl \
    ca-certificates \
    psmisc \
    && rm -rf /var/lib/apt/lists/*

# Install official standalone ttyd binary (supports both x86_64 and arm64)
RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -o /usr/local/bin/ttyd ; \
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.aarch64 -o /usr/local/bin/ttyd ; \
    else \
        curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 -o /usr/local/bin/ttyd ; \
    fi && \
    chmod +x /usr/local/bin/ttyd

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
