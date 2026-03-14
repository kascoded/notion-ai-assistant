# Changelog

All notable changes to the Notion AI Assistant project.

## [0.4.0] - 2026-03-14

### 🚀 Added

- **`interfaces/scheduler.py`** — Proactive check-in scheduler:
  - Morning brief (8am, configurable via `MORNING_CHECKIN_HOUR`) — includes today's Google Calendar events when configured
  - Evening habit nudge (9pm, configurable via `EVENING_CHECKIN_HOUR`)
  - Weekly review (Fridays at 5pm)
  - Timezone-aware via `TZ` env var (defaults to `America/Los_Angeles`)
- **`clients/google_calendar_client.py`** — Async Google Calendar client:
  - Queries all user calendars (not just primary) and merges results
  - `get_events(date_iso)` — fetch events for any date, sorted with all-day first
  - `get_current_and_next()` — what's happening right now + next upcoming event
  - `create_event(summary, start, end)` — create events with 1-hour default duration
  - Timezone-correct using local `TZ` env var; uses `asyncio.get_running_loop()` for Python 3.13 safety
  - Gracefully skipped when `GOOGLE_*` env vars are not set
- **`ActionType.CALENDAR`** — New action type routing to Google Calendar instead of Notion
  - Sub-actions: `query` (list events), `current` (now/next), `create` (new event)
- **`scripts/google_auth.py`** — One-time OAuth setup script for getting Google refresh token
- **Date-filtered queries** — `handle_search` now accepts `target_date` to query databases by date property:
  - `project_management` → `Deadline`
  - `workout_schedule` → `date`
  - `meal_planning` → `date`
  - `expense_tracker` → `Due Date`
  - `blog_content` → `date`
  - `zettelkasten` → `date`
- **New Telegram commands**: `/refresh_controls`, `/refresh_schemas`, `/preview`, `/checkin`
- **New AI controls in Notion**: Calendar Query Rules (priority 8), Project Management Query Rules (priority 7)
- **New dependencies**: `google-auth`, `google-api-python-client`, `google-auth-oauthlib`

### 🐛 Fixed

- **Telegram formatting** — All bot responses converted from MarkdownV2 to HTML (`<b>`, `<code>` tags); fixes formatting errors across all commands
- **Rate limit retry** — Added exponential backoff (`utils/retry.py`) for Notion 429 errors with `Retry-After` header support
- **Outbound message logging** — All Telegram messages now logged with `user_id`, `msg_id`, `duration_ms`, and preview
- **Cold start reliability** — MCP `post_init` failures no longer crash the bot at startup; error is caught and surfaced gracefully
- **Controls initialization lock** — Fixed race condition where concurrent requests could double-initialize the controls loader
- **Parse error handling** — LLM parsing failures now surface a real error message to the user instead of a silent fallback
- **Habits routing** — Date-aware updates (resolves "yesterday", "last Monday" to ISO dates); correct DB name enforcement; habits no longer accidentally routed to other databases
- **READ handler** — Now properly fetches and returns page content with section extraction; formatter returns Notion link
- **Prompt injection protection** — Curly braces in AI control content are escaped before being injected into LangChain prompt templates
- **Calendar routing** — Fixed `database` field default from `"calendar"` to `"zettelkasten"` so non-calendar intents are unaffected
- **Calendar timezone** — Query windows use local timezone (not UTC midnight); fixes events appearing on wrong dates
- **Calendar event loop** — `get_event_loop()` replaced with `get_running_loop()` (required for Python 3.13)
- **Zero-duration events** — Calendar `create_event` defaults end time to start + 1 hour when not provided
- **In-progress event detection** — `get_current_and_next()` looks back 4 hours to catch events already underway

### ♻️ Changed

- Calendar response format: shows day of week (`Saturday, March 14`), time range (`1:00 PM – 2:00 PM`), no date on each line
- Calendar queries now pull from all user calendars (Miras Work, Miras Life, Birthdays, etc.) and merge results

---

## [0.3.0] - 2026-01-24

### 🎯 Notion-Based AI Controls

Major architectural upgrade: **parsing logic is now driven by Notion pages** instead of hardcoded prompts. Edit your agent's behavior by updating Notion—no code changes or redeployment needed.

#### Added

- **`controls_loader.py`** — New module that fetches AI controls from the `ai_controls` Notion database
  - Caches controls with configurable TTL (default: 5 minutes)
  - Filters by `control_type`, `context`, or `target_database`
  - Formats controls for LLM system prompt injection
  - Singleton pattern with `get_controls_loader()` for global access

- **AI Controls Database Schema** — Structured control types in Notion:
  - `routing_logic` — Rules for routing input to databases
  - `prompt_template` — Reusable prompts for parsing
  - `quality_criteria` — Standards for content creation
  - `style_guide` — Voice/tone definitions
  - `validation_rule` — Quality gates before execution
  - `output_format` — Response formatting rules
  - `persona_definition` — Agent personality
  - `workflow_step` — Multi-step process definitions

- **Pre-built Controls** — Six foundational controls created:
  - Master Router (priority 1) — Top-level routing decisions
  - Word Dump Parser (priority 5) — Main parsing prompt
  - Zettelkasten Standards (priority 10) — Knowledge note quality
  - Project Parsing Rules (priority 10) — Task extraction
  - Habit Tracker Rules (priority 10) — Habit logging
  - Calorie Tracking Parser (priority 10) — Nutrition parsing

- **New Agent Methods**:
  - `refresh_controls()` — Force reload controls from Notion
  - `refresh_all()` — Reload both schemas and controls

#### Changed

- **`nl_parser.py`** — Now accepts `ControlsLoader` and injects controls into system prompt
  - Prompt cache invalidates when controls change
  - `_get_prompt_hash()` tracks both schema and controls state
  - Falls back gracefully if controls not initialized

- **`agent.py`** — Initializes controls alongside schemas on startup
  - Shows loaded controls count in ready message
  - `controls_loader` property exposed for external access

- **`config/__init__.py`** — Exports new controls module

#### Architecture

```
BEFORE (v0.2.x):
┌─────────────┐     ┌─────────────────────┐
│ User Input  │ ──▶ │ Hardcoded Prompts   │ ──▶ Parse
└─────────────┘     │ in nl_parser.py     │
                    └─────────────────────┘

AFTER (v0.3.0):
┌─────────────┐     ┌─────────────────────┐     ┌─────────────────┐
│ User Input  │ ──▶ │ ControlsLoader      │ ──▶ │ Dynamic Prompt  │ ──▶ Parse
└─────────────┘     │ (from Notion)       │     │ with <controls> │
                    └─────────────────────┘     └─────────────────┘
                              ▲
                              │
                    ┌─────────────────────┐
                    │ ai_controls DB      │
                    │ (editable in Notion)│
                    └─────────────────────┘
```

---

## [0.2.0] - 2026-01-23

### 🔧 Dynamic Schema Loading

Major upgrade from hardcoded database configurations to **runtime schema fetching** from the MCP server.

#### Added

- **`schema_manager.py`** — Dynamic schema management
  - Fetches database schemas from Notion via MCP on initialization
  - `DatabaseSchema` and `PropertySchema` dataclasses
  - Property validation and type coercion
  - Auto-generates parser prompts from actual database structure
  - Singleton pattern with `get_schema_manager()`

- **`initialize_schemas()`** — Async function to bootstrap schema loading

- **Schema-aware property handling**:
  - Validates properties against actual Notion database schemas
  - Suggests corrections for invalid select/multi-select values
  - Formats properties correctly for Notion API

#### Changed

- **`nl_parser.py`** — Now uses `SchemaManager` for database context
  - `generate_parser_prompt()` builds prompt from live schemas
  - `generate_database_examples()` creates keyword hints dynamically
  - Database name validation against actual workspace

- **`agent.py`** — Initializes schemas on startup via `SchemaManager`

- **`agent_nodes.py`** — Uses schema manager for property validation in routing

#### Removed

- Hardcoded `DATABASES` dictionary in `nl_parser.py`
- Manual database configuration requirements

#### Architecture

```
BEFORE (v0.1.x):
┌─────────────────────────────────────────┐
│ nl_parser.py                            │
│                                         │
│ DATABASES = {                           │
│   "zettelkasten": "notes, ideas...",   │  ◀── Hardcoded
│   "habits": "daily tracking...",        │
│   ...                                   │
│ }                                       │
└─────────────────────────────────────────┘

AFTER (v0.2.0):
┌─────────────────────────────────────────┐
│ SchemaManager                           │
│                                         │
│ async def initialize(mcp):              │
│   schemas = await mcp.list_databases()  │  ◀── Dynamic
│   for db in schemas:                    │
│     self.schemas[db.name] = db          │
└─────────────────────────────────────────┘
```

---

## [0.1.0] - 2026-01-22

### 🏗️ Project Modularization

Complete restructure from flat file layout to proper Python package architecture.

#### Added

- **Proper package structure** under `src/notion_assistant/`:
  ```
  src/notion_assistant/
  ├── __init__.py
  ├── agent.py              # Main LangGraph agent
  ├── clients/
  │   └── mcp_client.py     # FastMCP client wrapper
  ├── config/
  │   └── schema_manager.py # Database schema management
  ├── interfaces/
  │   └── telegram_bot.py   # Telegram interface
  ├── nodes/
  │   └── agent_nodes.py    # LangGraph node functions
  ├── parsers/
  │   └── nl_parser.py      # Natural language parser
  ├── states/
  │   └── state.py          # Agent state definitions
  └── tools/
      └── action_handlers.py # Notion action implementations
  ```

- **`pyproject.toml`** — Modern Python packaging with:
  - UV/hatchling build system
  - Proper dependency declarations
  - Development dependencies (pytest, ruff)

- **Entry points**:
  - `run.py` — CLI interface
  - `run_telegram.py` — Telegram bot

- **Multi-transport MCP client** — Supports STDIO, HTTP, and SSE transports

#### Changed

- Moved from flat `agents/` and `tools/` directories to nested package structure
- All imports now use `src.notion_assistant.*` paths
- Separated concerns:
  - `clients/` — External service connections
  - `config/` — Configuration and schema management
  - `interfaces/` — User-facing interfaces (CLI, Telegram)
  - `nodes/` — LangGraph workflow nodes
  - `parsers/` — Input parsing logic
  - `states/` — State machine definitions
  - `tools/` — Action handlers and utilities

#### Architecture

```
BEFORE (v0.0.x):
notion-ai-assistant/
├── agents/
│   └── notion_agent.py     # Everything in one file
├── tools/
│   ├── mcp_client.py
│   └── nl_parser.py
└── requirements.txt

AFTER (v0.1.0):
notion-ai-assistant/
├── src/
│   └── notion_assistant/
│       ├── agent.py
│       ├── clients/
│       ├── config/
│       ├── interfaces/
│       ├── nodes/
│       ├── parsers/
│       ├── states/
│       └── tools/
├── pyproject.toml
├── run.py
└── run_telegram.py
```

---

## Version Summary

| Version | Date | Highlight |
|---------|------|-----------|
| 0.4.0 | 2026-03-14 | Google Calendar integration, proactive scheduler, HTML formatting, rate-limit retry |
| 0.3.0 | 2026-01-24 | Notion-based AI controls (no-code behavior editing) |
| 0.2.0 | 2026-01-23 | Dynamic schema loading from MCP |
| 0.1.0 | 2026-01-22 | Project modularization & proper packaging |

---

## Migration Guide

### From 0.2.x to 0.3.0

1. **Create `ai_controls` database** in Notion with properties:
   - `Name` (title)
   - `control_type` (select)
   - `context` (multi-select)
   - `target_database` (multi-select)
   - `priority` (number)
   - `active` (checkbox)

2. **Add to your MCP server's `databases.yaml`**:
   ```yaml
   ai_controls:
     database_id: "your-database-id"
   ```

3. **No code changes required** — the new modules are backward compatible

### From 0.1.x to 0.2.0

1. Remove any hardcoded database configurations
2. Ensure MCP server has `notion_get_data_source` tool available
3. Agent will auto-fetch schemas on initialization

### From 0.0.x to 0.1.0

1. Move code to new package structure
2. Update all imports to `src.notion_assistant.*`
3. Replace `requirements.txt` with `pyproject.toml`
4. Use `uv` for dependency management
