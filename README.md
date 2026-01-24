# Notion AI Assistant

Natural language interface to your Notion workspace using LangGraph and FastMCP.

> **v0.3.0** — Now with Notion-based AI controls. Edit your agent's behavior directly in Notion—no code changes needed.

## Overview

This LangGraph-based agent processes natural language input and automatically routes operations to your Notion databases via your FastMCP server. The parsing logic itself is stored in Notion, making it fully configurable without touching code.

```
User Input → AI Controls (from Notion) → LangGraph Agent → FastMCP → Notion API
```

### Key Features

- 🧠 **Natural Language Processing** — Understands conversational input
- 🎯 **Smart Multi-Database Routing** — One input can create entries across multiple databases
- 📝 **Dynamic Schema Loading** — Adapts to your actual Notion workspace structure
- 🎛️ **Notion-Based Controls** — Parsing rules live in Notion, editable without code
- ⚡ **Multi-Transport Support** — STDIO (local), HTTP (cloud), SSE (legacy)
- 📱 **Telegram Interface** — Mobile-friendly access from anywhere

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         NOTION                                  │
│  ┌──────────────────┐    ┌──────────────────────────────────┐  │
│  │  ai_controls DB  │    │  Your Databases                  │  │
│  │  • Master Router │    │  • zettelkasten  • habits        │  │
│  │  • Parser Rules  │    │  • projects      • calories      │  │
│  │  • Quality Gates │    │  • blog          • expenses      │  │
│  └────────┬─────────┘    └──────────────────────────────────┘  │
└───────────┼─────────────────────────────────────────────────────┘
            │ fetch on init
            ▼
┌───────────────────────────────────────────────────────────────┐
│                    notion-ai-assistant                        │
│                                                               │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────────────┐ │
│  │ Controls    │──▶│ NL Parser   │──▶│ LangGraph Agent     │ │
│  │ Loader      │   │ (dynamic)   │   │ • parse             │ │
│  └─────────────┘   └─────────────┘   │ • route             │ │
│                                       │ • execute (parallel)│ │
│  ┌─────────────┐                     │ • format            │ │
│  │ Schema      │─────────────────────▶└──────────┬──────────┘ │
│  │ Manager     │                                 │            │
│  └─────────────┘                                 ▼            │
│                                       ┌─────────────────────┐ │
│                                       │ MCP Client          │ │
│                                       │ (STDIO/HTTP/SSE)    │ │
│                                       └──────────┬──────────┘ │
└──────────────────────────────────────────────────┼────────────┘
                                                   │
                                                   ▼
                                        ┌─────────────────────┐
                                        │ FastMCP Server      │
                                        │ (kas-fastmcp)       │
                                        └─────────────────────┘
```

## Project Structure

```
notion-ai-assistant/
├── src/notion_assistant/
│   ├── agent.py              # Main LangGraph agent & NotionAssistant class
│   ├── clients/
│   │   └── mcp_client.py     # FastMCP client (multi-transport)
│   ├── config/
│   │   ├── schema_manager.py # Dynamic database schema loading
│   │   └── controls_loader.py# AI controls from Notion
│   ├── interfaces/
│   │   └── telegram_bot.py   # Telegram bot interface
│   ├── nodes/
│   │   └── agent_nodes.py    # LangGraph node functions
│   ├── parsers/
│   │   └── nl_parser.py      # Natural language parser
│   ├── states/
│   │   └── state.py          # Agent state definitions
│   └── tools/
│       └── action_handlers.py# Notion action implementations
├── run.py                    # CLI entry point
├── run_telegram.py           # Telegram bot entry point
├── pyproject.toml            # Dependencies & build config
└── CHANGELOG.md              # Version history
```

## Quick Start

### Prerequisites

- Python 3.10+
- A running [FastMCP Notion server](https://github.com/kascoded/kas-fastmcp)
- OpenAI API key
- (Optional) Telegram bot token

### Installation

```bash
# Clone the repository
git clone https://github.com/kascoded/notion-ai-assistant
cd notion-ai-assistant

# Install with uv (recommended)
uv sync

# Or with pip
pip install -e .
```

### Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your credentials:
OPENAI_API_KEY=sk-...
NOTION_MCP_URL=https://your-mcp-server.fastmcp.cloud/mcp
# Or for local development:
NOTION_MCP_PATH=/path/to/kas-fastmcp/main.py
```

### Set Up AI Controls Database

Create an `ai_controls` database in Notion with these properties:

| Property | Type | Purpose |
|----------|------|---------|
| Name | Title | Control name |
| control_type | Select | routing_logic, prompt_template, quality_criteria, etc. |
| context | Multi-select | execution, content_creation, technical, creative |
| target_database | Multi-select | Which databases this control applies to |
| priority | Number | Lower = higher priority (processed first) |
| active | Checkbox | Enable/disable without deleting |

Add the database to your MCP server's `databases.yaml`:

```yaml
ai_controls:
  database_id: "your-ai-controls-database-id"
```

### Run

```bash
# Interactive CLI
uv run python run.py

# Or with Telegram
uv run python run_telegram.py
```

## Usage Examples

### Multi-Intent Input

```
You: Ate eggs for breakfast, did my morning workout, and had an idea about 
     using webhooks for real-time Notion sync

Response:
✅ Created 'Eggs' in calorie_tracker
✅ Updated habits (workout: ✓)
✅ Created 'Webhooks for real-time Notion sync' in zettelkasten
```

### Creating Notes

```
You: Create a note about design tokens with tags design-systems, css

Response:
✅ Created 'Design Tokens' in zettelkasten
🔗 https://notion.so/...
```

### Searching

```
You: Search for notes about machine learning

Response:
🔍 Found 5 results:
1. Neural Network Basics
2. PyTorch vs TensorFlow
3. ML Pipeline Architecture
...
```

### Task Management

```
You: Add a task to review the API docs by Friday for miraskas.com

Response:
✅ Created 'Review API docs' in project_management
📅 Deadline: Friday
🏷️ Account: miraskas.com
```

## AI Controls System

The `ai_controls` database stores parsing instructions that get injected into the LLM's system prompt at runtime.

### Control Types

| Type | Purpose | Example |
|------|---------|---------|
| `routing_logic` | Rules for routing to databases | "Keywords like 'ate', 'meal' → calorie_tracker" |
| `prompt_template` | Reusable parsing prompts | Word dump parser instructions |
| `quality_criteria` | Standards for content | Zettelkasten note guidelines |
| `style_guide` | Voice/tone definitions | Blog writing style |
| `validation_rule` | Quality gates | Required fields before creation |

### Pre-Built Controls

The system comes with foundational controls:

1. **Master Router** (priority 1) — Top-level routing decisions
2. **Word Dump Parser** (priority 5) — Main parsing prompt for unstructured input
3. **Zettelkasten Standards** (priority 10) — Knowledge note quality criteria
4. **Project Parsing Rules** (priority 10) — Task/project extraction
5. **Habit Tracker Rules** (priority 10) — Habit logging patterns
6. **Calorie Tracking Parser** (priority 10) — Food/nutrition parsing

### Editing Controls

1. Open your `ai_controls` database in Notion
2. Click on any control page
3. Edit the page content (instructions, examples, rules)
4. Changes take effect within 5 minutes (or call `refresh_controls()`)

No code changes. No redeployment. Just edit Notion.

## Interfaces

### CLI

```bash
uv run python run.py
```

Interactive terminal with Rich formatting, typing indicators, and colored output.

### Telegram Bot

```bash
# Set up in .env:
TELEGRAM_BOT_TOKEN=your-token-from-botfather
TELEGRAM_ALLOWED_USERS=123456789,987654321

# Run:
uv run python run_telegram.py
```

**Commands:**
| Command | Description |
|---------|-------------|
| `/start` | Welcome message |
| `/help` | Usage examples |
| `/databases` | List available databases |
| `/status` | System status |
| `/refresh` | Reload schemas and controls |

## API Reference

### NotionAssistant

High-level interface for the agent.

```python
from src.notion_assistant.agent import NotionAssistant

assistant = NotionAssistant()
await assistant.initialize()  # Loads schemas + controls

# Process natural language
response = await assistant.process("Create a note about FastMCP")

# Refresh configurations
await assistant.refresh_controls()  # Reload AI controls from Notion
await assistant.refresh_schemas()   # Reload database schemas
await assistant.refresh_all()       # Reload everything
```

### ControlsLoader

Manages AI controls from Notion.

```python
from src.notion_assistant.config import ControlsLoader, get_controls_loader

loader = get_controls_loader()
await loader.initialize(mcp_client)

# Get all active controls
all_controls = loader.controls

# Filter by type
routing_rules = loader.get_by_type("routing_logic")

# Filter by target database
zettel_controls = loader.get_by_database("zettelkasten")

# Format for prompt injection
prompt_section = loader.format_routing_prompt()
```

### SchemaManager

Dynamic database schema management.

```python
from src.notion_assistant.config import SchemaManager, get_schema_manager

manager = get_schema_manager()
await manager.initialize(mcp_client)

# Get database names
databases = manager.database_names  # ['zettelkasten', 'habits', ...]

# Get schema for specific database
schema = manager.get_schema("zettelkasten")
print(schema.properties)  # {'title': {...}, 'tags': {...}, ...}

# Validate properties
fixed, warnings = manager.validate_properties("habits", {"workout": True})
```

### NotionMCPClient

FastMCP client with multi-transport support.

```python
from src.notion_assistant.clients import NotionMCPClient

# Auto-detect transport from environment
async with NotionMCPClient() as mcp:
    # Query database
    results = await mcp.query_database("zettelkasten", page_size=10)
    
    # Create page
    page = await mcp.create_page(
        database_name="zettelkasten",
        properties={"title": {"title": [{"text": {"content": "My Note"}}]}},
        content_markdown="# Hello World"
    )
    
    # Search
    results = await mcp.search("machine learning")

# Explicit transport
async with NotionMCPClient(url="https://mcp.example.com", transport="http") as mcp:
    ...
```

## Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | OpenAI API key for parsing |
| `NOTION_MCP_URL` | One of these | Remote MCP server URL |
| `NOTION_MCP_PATH` | One of these | Local MCP server script path |
| `NOTION_MCP_TOKEN` | If using auth | Bearer token for authenticated servers |
| `TELEGRAM_BOT_TOKEN` | For Telegram | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USERS` | For Telegram | Comma-separated user IDs |

### Model Configuration

In `nl_parser.py`:

```python
FAST_MODEL = "gpt-4o-mini"      # Primary model (cheap, fast)
SMART_MODEL = "gpt-4o"          # Escalation model (expensive, accurate)
CONFIDENCE_THRESHOLD = 0.7      # Escalate if confidence below this
```

### Cache TTL

In `controls_loader.py`:

```python
loader = ControlsLoader(cache_ttl=300)  # 5 minutes default
```

## Development

### Running Tests

```bash
uv run pytest
```

### Code Formatting

```bash
uv run ruff check --fix .
uv run black .
```

### Testing Individual Components

```bash
# Test parser with controls
uv run python -m src.notion_assistant.parsers.nl_parser

# Test controls loader
uv run python -m src.notion_assistant.config.controls_loader

# Test MCP connection
uv run python -c "
from src.notion_assistant.clients import NotionMCPClient
import asyncio

async def test():
    async with NotionMCPClient() as mcp:
        dbs = await mcp.list_databases()
        print(f'Connected! Found {len(dbs)} databases')

asyncio.run(test())
"
```

## Troubleshooting

### "Controls not loading"

1. Check `ai_controls` is in your MCP server's `databases.yaml`
2. Verify the database has the required properties
3. Ensure at least one control has `active: ✓`

### "Unknown database" errors

1. Run `await assistant.refresh_schemas()`
2. Check MCP server has access to the database
3. Use exact database names from your config

### "MCP connection failed"

1. For local: verify `NOTION_MCP_PATH` points to valid `main.py`
2. For remote: check `NOTION_MCP_URL` and `NOTION_MCP_TOKEN`
3. Test MCP server independently first

### "Low confidence / wrong routing"

1. Edit the relevant control in `ai_controls`
2. Add more examples to the control's page content
3. Adjust keyword hints and routing rules
4. Call `/refresh` in Telegram or `refresh_controls()` in code

## Roadmap

- [x] Multi-intent parsing
- [x] Dynamic schema loading
- [x] Notion-based AI controls
- [x] Telegram interface
- [ ] Voice input support
- [ ] Batch operations
- [ ] Conversation memory
- [ ] Web dashboard for controls
- [ ] Multi-user support

## Contributing

Contributions welcome! Please read the [CHANGELOG](CHANGELOG.md) to understand the architecture evolution.

## License

MIT License — See [LICENSE](LICENSE)

## Related Projects

- [kas-fastmcp](https://github.com/kascoded/kas-fastmcp) — FastMCP Notion server
- [FastMCP](https://github.com/jlowin/fastmcp) — FastMCP framework
- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent orchestration

---

Built with ❤️ using LangGraph, FastMCP, and Notion
