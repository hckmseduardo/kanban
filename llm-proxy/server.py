#!/usr/bin/env python3
"""Simple LLM proxy that runs on host and forwards requests to Claude CLI.

This service runs on the host machine (not in Docker) and accepts HTTP requests
from containers, forwarding them to Claude CLI which has access to the macOS
Keychain credentials.

Usage:
    python server.py [port]

Example:
    python server.py 8888

Then containers can call:
    curl -X POST http://host.docker.internal:8888/query -d '{"prompt": "Hello"}'
"""

import asyncio
import json
import subprocess
import sys
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn


app = FastAPI(title="LLM Proxy", description="Forwards requests to Claude CLI")


class QueryRequest(BaseModel):
    prompt: str
    temperature: Optional[float] = 0.5
    max_tokens: Optional[int] = 4096


class QueryResponse(BaseModel):
    response: str
    error: Optional[str] = None


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest):
    """Send a prompt to Claude CLI and return the response."""
    try:
        # Run claude CLI with the prompt via stdin
        process = await asyncio.create_subprocess_exec(
            "claude",
            "-p",  # Print mode (non-interactive)
            "-",   # Read from stdin
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=request.prompt.encode()),
            timeout=300.0  # 5 minute timeout
        )

        if process.returncode != 0:
            error_msg = stderr.decode().strip() if stderr else "Unknown error"
            raise HTTPException(status_code=500, detail=f"Claude CLI error: {error_msg}")

        response_text = stdout.decode().strip()
        return QueryResponse(response=response_text)

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Claude CLI request timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Claude CLI not found. Make sure it's installed and in PATH.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8888
    print(f"Starting LLM Proxy on port {port}")
    print("Containers can call: http://host.docker.internal:{port}/query")
    uvicorn.run(app, host="0.0.0.0", port=port)
