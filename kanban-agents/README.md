# Kanban Agents

Multi-personality AI agents that interact with Kanban boards based on ticket status.

## Overview

Kanban Agents automatically processes tickets on your Kanban board using different AI agent personalities depending on the ticket's current status (column):

| Column | Agent | Personality |
|--------|-------|-------------|
| Backlog/Triage | 🔍 Triager | Analyzes, categorizes, estimates |
| Planning/To Do | 📋 Planner | Creates implementation plans |
| In Progress | 💻 Developer | Writes and commits code |
| Review | 🔎 Reviewer | Reviews code, suggests improvements |
| Testing | 🧪 Tester | Runs tests, validates changes |
| Blocked | 🔧 Unblocker | Investigates and resolves blockers |

## Quick Start

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/kanban-agents.git
cd kanban-agents

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env with your settings
```

### 2. Configuration

Edit `.env` with your settings:

```env
KANBAN_URL=https://myteam.example.com/api
BOARD_ID=your-board-id
REPO_PATH=/path/to/your/code/repo
ANTHROPIC_API_KEY=sk-ant-xxxxx
AGENT_LABEL=agent
```

### 3. Run

**Option A: Polling Mode** (checks for cards periodically)

```bash
python main.py poll --board-id <your-board-id>
```

**Option B: Webhook Server** (reacts to events in real-time)

```bash
python main.py server --port 8080
```

Then register the webhook in your Kanban:

```bash
curl -X POST https://myteam.example.com/api/webhooks \
  -H "Content-Type: application/json" \
  -d '{
    "name": "AI Agents",
    "url": "https://your-server.com/webhook",
    "events": ["card.created", "card.moved", "card.updated"],
    "secret": "your-webhook-secret"
  }'
```

## Usage

### Mark Cards for Processing

Add the `agent` label (or your configured label) to any card you want the AI to process.

### Agent Flow Example

1. **Create a card** in Backlog with label `agent`
2. **Triager** analyzes it, adds labels, estimates complexity
3. **Move to Planning** → **Planner** creates implementation plan
4. **Move to In Progress** → **Developer** writes code
5. **Move to Review** → **Reviewer** checks the code
6. **Move to Testing** → **Tester** validates changes
7. **Move to Done** → Complete!

### Process Single Card

```bash
python main.py process --card-id <card-id> --agent coder
```

### List Available Agents

```bash
python main.py list
```

## Docker

```bash
# Build
docker build -t kanban-agents .

# Run webhook server
docker run -p 8080:8080 \
  -e KANBAN_URL=https://myteam.example.com/api \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  -v /path/to/repo:/workspace \
  kanban-agents

# Run with docker-compose
docker compose up webhook-server

# Or polling mode
docker compose --profile polling up poller
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       KANBAN BOARD                          │
│  Backlog → Planning → In Progress → Review → Testing → Done │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    KANBAN AGENTS                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐    │
│  │ Triager  │  │ Planner  │  │ Developer│  │ Reviewer │    │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Controller / Webhook Server             │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                    CODE REPOSITORY                          │
│                    (Your GitHub repo)                       │
└─────────────────────────────────────────────────────────────┘
```

## Customization

### Add Custom Personalities

Edit `agents/personalities.py`:

```python
AGENT_PERSONALITIES["my_agent"] = {
    "name": "My Custom Agent",
    "emoji": "🎯",
    "description": "Does something specific",
    "system_prompt": """You are a custom agent...

    Your job:
    1. ...
    2. ...
    """
}
```

### Map to Custom Columns

Edit `agents/personalities.py` `get_agent_for_column()`:

```python
mappings = [
    (["my-column", "custom"], "my_agent"),
    # ... existing mappings
]
```

## API Reference

### Webhook Endpoints

- `POST /webhook` - Receive Kanban events
- `GET /health` - Health check
- `GET /agents` - List available agents

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `KANBAN_URL` | Kanban API base URL | `http://localhost:8000` |
| `BOARD_ID` | Default board ID | - |
| `REPO_PATH` | Code repository path | Current directory |
| `ANTHROPIC_API_KEY` | Anthropic API key | - |
| `AGENT_LABEL` | Label for agent cards | `agent` |
| `POLL_INTERVAL` | Polling interval (seconds) | `30` |
| `WEBHOOK_SECRET` | Webhook signature secret | - |
| `WEBHOOK_PORT` | Webhook server port | `8080` |

## Development

```bash
# Install dev dependencies
pip install -r requirements.txt

# Run tests
pytest

# Format code
black .
ruff check .
```

## License

MIT
