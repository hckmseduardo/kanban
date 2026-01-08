# LLM Proxy Architecture

## Overview

The LLM Proxy is a routing layer that manages LLM API requests from agents. It provides centralized configuration, request routing, rate limiting, and usage tracking for all LLM interactions across the platform.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            LLM Proxy Service                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                       API Gateway                                   │     │
│  │                                                                     │     │
│  │  POST /v1/chat/completions    (OpenAI-compatible)                  │     │
│  │  POST /v1/messages            (Anthropic-compatible)                │     │
│  │  GET  /health                                                       │     │
│  │  GET  /usage                                                        │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                    │                                         │
│                                    ▼                                         │
│  ┌────────────────────────────────────────────────────────────────────┐     │
│  │                      Request Router                                 │     │
│  │                                                                     │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │     │
│  │  │   Model     │  │    Rate     │  │   Usage     │                 │     │
│  │  │   Mapper    │  │   Limiter   │  │   Tracker   │                 │     │
│  │  └─────────────┘  └─────────────┘  └─────────────┘                 │     │
│  └────────────────────────────────────────────────────────────────────┘     │
│                                    │                                         │
│          ┌─────────────────────────┼─────────────────────────┐              │
│          │                         │                         │              │
│          ▼                         ▼                         ▼              │
│  ┌───────────────┐        ┌───────────────┐        ┌───────────────┐       │
│  │   Anthropic   │        │    OpenAI     │        │    Ollama     │       │
│  │   Provider    │        │   Provider    │        │   Provider    │       │
│  │               │        │               │        │               │       │
│  │  claude-*     │        │  gpt-4-*      │        │  llama2       │       │
│  │               │        │  gpt-3.5-*    │        │  codellama    │       │
│  └───────────────┘        └───────────────┘        └───────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────┐
                    │         LLM APIs              │
                    │                               │
                    │  api.anthropic.com            │
                    │  api.openai.com               │
                    │  localhost:11434 (Ollama)     │
                    └───────────────────────────────┘
```

## Directory Structure

```
llm-proxy/
├── app/
│   ├── main.py              # FastAPI application
│   ├── config.py            # Configuration settings
│   ├── routes/
│   │   ├── chat.py          # OpenAI-compatible endpoint
│   │   ├── messages.py      # Anthropic-compatible endpoint
│   │   └── usage.py         # Usage statistics
│   ├── providers/
│   │   ├── base.py          # Provider interface
│   │   ├── anthropic.py     # Anthropic provider
│   │   ├── openai.py        # OpenAI provider
│   │   └── ollama.py        # Ollama provider
│   ├── middleware/
│   │   ├── auth.py          # API key validation
│   │   ├── rate_limit.py    # Rate limiting
│   │   └── logging.py       # Request logging
│   └── services/
│       ├── router.py        # Model routing
│       └── usage.py         # Usage tracking
├── Dockerfile
└── requirements.txt
```

## API Endpoints

### OpenAI-Compatible Endpoint
```
POST /v1/chat/completions
```

Request:
```json
{
  "model": "gpt-4-turbo",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "temperature": 0.7,
  "max_tokens": 1000,
  "tools": [...]
}
```

Response:
```json
{
  "id": "chatcmpl-xxx",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gpt-4-turbo",
  "choices": [{
    "index": 0,
    "message": {
      "role": "assistant",
      "content": "Hello! How can I help you today?"
    },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 20,
    "completion_tokens": 10,
    "total_tokens": 30
  }
}
```

### Anthropic-Compatible Endpoint
```
POST /v1/messages
```

Request:
```json
{
  "model": "claude-sonnet-4-20250514",
  "system": "You are a helpful assistant.",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "max_tokens": 1000,
  "tools": [...]
}
```

Response:
```json
{
  "id": "msg-xxx",
  "type": "message",
  "role": "assistant",
  "content": [{
    "type": "text",
    "text": "Hello! How can I help you today?"
  }],
  "model": "claude-sonnet-4-20250514",
  "stop_reason": "end_turn",
  "usage": {
    "input_tokens": 20,
    "output_tokens": 10
  }
}
```

### Usage Endpoint
```
GET /usage
GET /usage?workspace=my-project
GET /usage?from=2024-01-01&to=2024-01-31
```

Response:
```json
{
  "period": {
    "from": "2024-01-01",
    "to": "2024-01-31"
  },
  "total": {
    "requests": 1500,
    "input_tokens": 500000,
    "output_tokens": 150000,
    "cost_usd": 25.50
  },
  "by_model": {
    "claude-sonnet-4-20250514": {
      "requests": 1000,
      "input_tokens": 400000,
      "output_tokens": 120000,
      "cost_usd": 20.00
    },
    "gpt-4-turbo": {
      "requests": 500,
      "input_tokens": 100000,
      "output_tokens": 30000,
      "cost_usd": 5.50
    }
  },
  "by_workspace": {
    "my-project": {
      "requests": 800,
      "cost_usd": 15.00
    }
  }
}
```

## Model Routing

### Model Mapping
```python
MODEL_ROUTES = {
    # Anthropic models
    "claude-opus-4-5-20251101": ("anthropic", "claude-opus-4-5-20251101"),
    "claude-sonnet-4-20250514": ("anthropic", "claude-sonnet-4-20250514"),
    "claude-3-haiku-20240307": ("anthropic", "claude-3-haiku-20240307"),

    # OpenAI models
    "gpt-4-turbo": ("openai", "gpt-4-turbo"),
    "gpt-4": ("openai", "gpt-4"),
    "gpt-3.5-turbo": ("openai", "gpt-3.5-turbo"),

    # Ollama models (local)
    "llama2": ("ollama", "llama2"),
    "codellama": ("ollama", "codellama"),
    "mistral": ("ollama", "mistral"),

    # Aliases
    "default": ("anthropic", "claude-sonnet-4-20250514"),
    "fast": ("anthropic", "claude-3-haiku-20240307"),
    "smart": ("anthropic", "claude-opus-4-5-20251101"),
    "local": ("ollama", "llama2"),
}
```

### Router Implementation
```python
class ModelRouter:
    def __init__(self, config: RouterConfig):
        self.providers = {
            "anthropic": AnthropicProvider(config.anthropic),
            "openai": OpenAIProvider(config.openai),
            "ollama": OllamaProvider(config.ollama),
        }

    def route(self, model: str) -> Tuple[str, str]:
        """Route model name to provider and actual model ID."""
        if model in MODEL_ROUTES:
            return MODEL_ROUTES[model]

        # Try to infer provider from model name
        if model.startswith("claude"):
            return ("anthropic", model)
        elif model.startswith("gpt"):
            return ("openai", model)
        else:
            return ("ollama", model)

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        provider_name, model_id = self.route(request.model)
        provider = self.providers[provider_name]
        return await provider.complete(request.with_model(model_id))
```

## Rate Limiting

### Configuration
```python
RATE_LIMITS = {
    "default": {
        "requests_per_minute": 60,
        "tokens_per_minute": 100000
    },
    "by_workspace": {
        "premium-workspace": {
            "requests_per_minute": 120,
            "tokens_per_minute": 200000
        }
    },
    "by_model": {
        "claude-opus-4-5-20251101": {
            "requests_per_minute": 20,
            "tokens_per_minute": 50000
        }
    }
}
```

### Implementation
```python
class RateLimiter:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def check_limit(
        self,
        workspace: str,
        model: str
    ) -> Tuple[bool, Optional[int]]:
        """Check if request is within rate limits.

        Returns:
            (allowed, retry_after_seconds)
        """
        key = f"ratelimit:{workspace}:{model}"
        current = await self.redis.get(key)

        limits = self.get_limits(workspace, model)

        if current and int(current) >= limits["requests_per_minute"]:
            ttl = await self.redis.ttl(key)
            return (False, ttl)

        await self.redis.incr(key)
        await self.redis.expire(key, 60)
        return (True, None)
```

## Usage Tracking

### Data Model
```python
class UsageRecord(BaseModel):
    timestamp: datetime
    workspace: str
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    request_duration_ms: int
    cost_usd: float
```

### Storage
```python
class UsageTracker:
    def __init__(self, redis: Redis):
        self.redis = redis

    async def record(self, usage: UsageRecord):
        """Record usage data."""
        # Store in Redis sorted set by timestamp
        key = f"usage:{usage.workspace}:{usage.model}"
        await self.redis.zadd(
            key,
            {json.dumps(usage.dict()): usage.timestamp.timestamp()}
        )

        # Update running totals
        totals_key = f"usage_totals:{usage.workspace}"
        await self.redis.hincrby(totals_key, "requests", 1)
        await self.redis.hincrby(totals_key, "input_tokens", usage.input_tokens)
        await self.redis.hincrby(totals_key, "output_tokens", usage.output_tokens)
        await self.redis.hincrbyfloat(totals_key, "cost_usd", usage.cost_usd)

    async def get_usage(
        self,
        workspace: str = None,
        from_date: datetime = None,
        to_date: datetime = None
    ) -> UsageReport:
        """Get usage statistics."""
        # Query and aggregate usage data
        ...
```

### Cost Calculation
```python
MODEL_PRICING = {
    # Anthropic (per million tokens)
    "claude-opus-4-5-20251101": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},

    # OpenAI (per million tokens)
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},

    # Ollama (local, free)
    "llama2": {"input": 0.00, "output": 0.00},
}

def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
    return (
        (input_tokens / 1_000_000) * pricing["input"] +
        (output_tokens / 1_000_000) * pricing["output"]
    )
```

## Authentication

### API Key Validation
```python
async def validate_api_key(request: Request) -> WorkspaceContext:
    """Validate API key and return workspace context."""
    auth_header = request.headers.get("Authorization")

    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(401, "Missing or invalid authorization")

    token = auth_header.split(" ")[1]

    # Check if it's a workspace token
    workspace = await verify_workspace_token(token)
    if workspace:
        return WorkspaceContext(
            workspace=workspace,
            permissions=["llm:complete"]
        )

    # Check if it's a platform token
    if token == settings.platform_api_key:
        return WorkspaceContext(
            workspace="platform",
            permissions=["llm:complete", "usage:read"]
        )

    raise HTTPException(401, "Invalid API key")
```

## Fallback Strategy

### Provider Fallback
```python
FALLBACK_CHAIN = {
    "anthropic": ["openai", "ollama"],
    "openai": ["anthropic", "ollama"],
    "ollama": []  # Local, no fallback
}

async def complete_with_fallback(request: CompletionRequest) -> CompletionResponse:
    provider_name, model = router.route(request.model)
    providers_to_try = [provider_name] + FALLBACK_CHAIN.get(provider_name, [])

    last_error = None
    for provider_name in providers_to_try:
        try:
            provider = router.providers[provider_name]
            return await provider.complete(request)
        except ProviderError as e:
            last_error = e
            logger.warning(f"Provider {provider_name} failed: {e}")
            continue

    raise last_error or ProviderError("All providers failed")
```

## Configuration

### Environment Variables
```bash
# Server
PORT=8081

# API Keys (from Key Vault)
ANTHROPIC_API_KEY=<from-keyvault>
OPENAI_API_KEY=<from-keyvault>

# Ollama (local)
OLLAMA_BASE_URL=http://ollama:11434

# Redis
REDIS_URL=redis://redis:6379

# Platform
PLATFORM_API_KEY=<platform-key>

# Rate Limiting
DEFAULT_REQUESTS_PER_MINUTE=60
DEFAULT_TOKENS_PER_MINUTE=100000

# Logging
LOG_REQUESTS=true
LOG_RESPONSES=false  # Privacy
```

## Request Flow

```
Agent                      LLM Proxy                    Provider
  │                            │                            │
  │  1. POST /v1/messages      │                            │
  ├───────────────────────────►│                            │
  │                            │                            │
  │                            │  2. Validate API key       │
  │                            │                            │
  │                            │  3. Check rate limits      │
  │                            │                            │
  │                            │  4. Route to provider      │
  │                            │                            │
  │                            │  5. Forward request        │
  │                            ├───────────────────────────►│
  │                            │                            │
  │                            │  6. Receive response       │
  │                            │◄───────────────────────────┤
  │                            │                            │
  │                            │  7. Track usage            │
  │                            │                            │
  │  8. Return response        │                            │
  │◄───────────────────────────┤                            │
```

## Streaming Support

### Implementation
```python
@app.post("/v1/chat/completions")
async def chat_completions(request: ChatRequest):
    if request.stream:
        return StreamingResponse(
            stream_completion(request),
            media_type="text/event-stream"
        )
    else:
        return await complete(request)

async def stream_completion(request: ChatRequest):
    provider_name, model = router.route(request.model)
    provider = router.providers[provider_name]

    async for chunk in provider.stream(request):
        yield f"data: {json.dumps(chunk)}\n\n"

    yield "data: [DONE]\n\n"
```

## Related Documentation
- [Overview](./overview.md)
- [Kanban Agents Architecture](./kanban-agents.md)
- [Infrastructure Architecture](./infrastructure.md)
