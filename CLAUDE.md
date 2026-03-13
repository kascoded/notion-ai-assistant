# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A LangGraph agent (v0.3.0) that processes natural language and routes operations to Notion databases through the `kas-fastmcp` MCP server. Parsing behavior is driven by an `ai_controls` Notion database — no hardcoded prompts.

## Commands

```bash
# Install dependencies
uv sync

# Run interactive CLI
uv run python run.py

# Run Telegram bot
uv run python run_telegram.py

# Lint / format
uv run ruff check --fix .
uv run black .

# Tests (no automated suite yet)
uv run pytest
```

**Testing individual components:**
```bash
# Test MCP connection
uv run python -c "
from src.notion_assistant.clients import NotionMCPClient
import asyncio
async def test():
    async with NotionMCPClient() as mcp:
        dbs = await mcp.list_databases()
        print(f'Connected! {len(dbs)} databases')
asyncio.run(test())
"

# Test parser or controls loader standalone
uv run python -m src.notion_assistant.parsers.nl_parser
uv run python -m src.notion_assistant.config.controls_loader
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Yes | LLM for parsing |
| `NOTION_MCP_URL` | One of | Remote MCP server URL |
| `NOTION_MCP_PATH` | One of | Local path to `kas-fastmcp/main.py` |
| `NOTION_MCP_TOKEN` | If auth | Bearer token for remote server |
| `TELEGRAM_BOT_TOKEN` | Telegram | Bot token from @BotFather |
| `TELEGRAM_ALLOWED_USERS` | Telegram | Comma-separated Telegram user IDs |

## Architecture

### LangGraph Pipeline

```
User Input
    ↓
parse_input_node     — NL → structured intents (multi-intent, confidence-based escalation)
    ↓
router_node          — validates intents against schemas, builds execution plan
    ↓
execute_intents_node — runs parallel-safe ops via asyncio.gather, sequential ops one-by-one
    ↓
format_response_node — assembles human-readable response
```

**State** flows through `AgentState` (TypedDict in `states/state.py`): `user_input → parsed → execution_plan → intent_results → response`.

### Key Design Patterns

**Singletons via `get_*` functions** — `get_schema_manager()` and `get_controls_loader()` return module-level singletons. All nodes use these instead of instantiating their own objects. Never create new `SchemaManager` or `ControlsLoader` instances directly.

**`NotionMCPClient` as async context manager** — opened fresh for each agent run (and for refresh operations). Supports three transports auto-detected from env: HTTP (`NOTION_MCP_URL`), STDIO (`NOTION_MCP_PATH`), or SSE (legacy).

**Two-model parsing** — `nl_parser.py` uses `gpt-4o-mini` by default; escalates to `gpt-4o` if confidence < 0.7. Prompt is built dynamically from live schemas + AI controls and cached (invalidated when schemas or controls change).

**AI Controls** — `controls_loader.py` fetches the `ai_controls` Notion database on init and injects its page content into the LLM system prompt. Controls are cached with a 5-minute TTL. Control types: `routing_logic`, `prompt_template`, `quality_criteria`, `style_guide`, `validation_rule`, `output_format`, `persona_definition`, `workflow_step`.

### Module Map

```
src/notion_assistant/
├── agent.py              # NotionAssistant class + build_agent() LangGraph builder
├── clients/
│   └── mcp_client.py     # NotionMCPClient — wraps FastMCP, multi-transport
├── config/
│   ├── schema_manager.py # SchemaManager — fetches/caches DB schemas from MCP
│   └── controls_loader.py# ControlsLoader — fetches AI controls from Notion
├── interfaces/
│   └── telegram_bot.py   # Telegram bot (/start /help /databases /status /refresh)
├── nodes/
│   └── agent_nodes.py    # Four LangGraph node functions
├── parsers/
│   └── nl_parser.py      # NaturalLanguageParser — two-model, dynamic prompt
├── states/
│   └── state.py          # AgentState, IntentResult TypedDicts
└── tools/
    └── action_handlers.py# handle_create/search/read/update/append
```

## Adding a New Action Type

1. Add to `ActionType` enum in `parsers/nl_parser.py`
2. Add handler `handle_<action>` in `tools/action_handlers.py`
3. Wire it in `nodes/agent_nodes.py` → `_execute_single_intent()`
4. Add formatting in `format_response_node` / `_format_single_result()`

## Relationship to `kas-fastmcp`

This project is a consumer of `kas-fastmcp`. All Notion API calls go through `NotionMCPClient` → MCP tools. Do not call the Notion API directly. Database names used here must match the keys in `kas-fastmcp/databases.yaml`.
