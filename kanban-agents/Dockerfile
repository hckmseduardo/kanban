# Kanban Agents Docker Image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create non-root user
RUN useradd -m -u 1000 agent && chown -R agent:agent /app
USER agent

# Default environment variables
ENV KANBAN_URL=http://localhost:8000 \
    REPO_PATH=/workspace \
    AGENT_LABEL=agent \
    POLL_INTERVAL=30 \
    WEBHOOK_PORT=8080 \
    LOG_LEVEL=INFO

# Expose webhook port
EXPOSE 8080

# Default command (can be overridden)
CMD ["python", "main.py", "server", "--port", "8080"]
