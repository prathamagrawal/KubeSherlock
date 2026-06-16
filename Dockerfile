FROM python:3.11-slim

LABEL org.opencontainers.image.source="https://github.com/yourusername/kubesherlock"
LABEL org.opencontainers.image.description="AI-powered Kubernetes incident investigation agent"

WORKDIR /app

# Install dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY k8s_mcp/ ./k8s_mcp/
COPY agent/ ./agent/
COPY database/ ./database/
COPY config.env.example ./config.env

# Create non-root user
RUN useradd -m -u 1000 kubesherlock && \
    chown -R kubesherlock:kubesherlock /app
USER kubesherlock

# Default to watcher mode
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "agent.watcher"]
