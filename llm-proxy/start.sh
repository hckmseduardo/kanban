#!/bin/bash
# Start the LLM Proxy service
# This runs on the host and forwards requests to Claude CLI

cd "$(dirname "$0")"

# Check if Claude CLI is available
if ! command -v claude &> /dev/null; then
    echo "Error: Claude CLI not found. Install it first with: npm install -g @anthropic-ai/claude-code"
    exit 1
fi

# Check if required Python packages are installed
if ! python3 -c "import fastapi, uvicorn, pydantic" 2>/dev/null; then
    echo "Installing required Python packages..."
    pip3 install fastapi uvicorn pydantic
fi

# Default port
PORT="${1:-8888}"

echo "Starting LLM Proxy on port $PORT"
echo "Containers can call: http://host.docker.internal:$PORT/query"
echo ""

python3 server.py "$PORT"
