"""
AI Controls Loader

Fetches agent instructions from the ai_controls Notion database and injects
them into the parser's system prompt. This enables no-code modifications to
agent behavior - just edit Notion, no redeploy needed.

Architecture:
    Notion ai_controls DB → ControlsLoader → System Prompt Injection → Parser

Hierarchy System:
    - Global controls (no target_database) → ALWAYS included
    - Database-specific controls → Only included when that database is detected
    
    Detection happens via lightweight keyword matching before the LLM call,
    reducing prompt size and improving relevance.

Usage:
    loader = ControlsLoader()
    await loader.initialize(mcp_client)
    
    # Get controls for specific input (uses keyword detection)
    prompt_section = loader.format_for_input("ate eggs, did workout")
    
    # Or get all controls (old behavior)
    prompt_section = loader.format_for_prompt()
"""
import asyncio
import time
import re
from typing import Dict, Any, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class ControlType(str, Enum):
    """Types of controls available in ai_controls database."""
    ROUTING_LOGIC = "routing_logic"
    STYLE_GUIDE = "style_guide"
    QUALITY_CRITERIA = "quality_criteria"
    OUTPUT_FORMAT = "output_format"
    PERSONA_DEFINITION = "persona_definition"
    WORKFLOW_STEP = "workflow_step"
    VALIDATION_RULE = "validation_rule"
    PROMPT_TEMPLATE = "prompt_template"


# ========================================
# Keyword Detection for Database Routing
# ========================================

# Maps keywords/phrases to database names
# Used for lightweight pre-detection before LLM call
DATABASE_KEYWORDS: Dict[str, List[str]] = {
    "zettelkasten": [
        "note", "notes", "idea", "ideas", "thought", "thoughts", 
        "learning", "learnings", "research", "concept", "concepts",
        "insight", "insights", "knowledge", "remember", "capture",
        "fleeting", "permanent note", "quick capture"
    ],
    "habit_tracker": [
        "habit", "habits", "streak", "daily", "routine",
        "workout", "worked out", "exercised", "exercise",
        "read", "reading", "meditate", "meditated", "meditation",
        "journal", "journaled", "journaling", "stretch", "stretched",
        "draw", "drawing", "drew", "sleep", "slept", "woke"
    ],
    "project_management": [
        "task", "tasks", "project", "projects", "deadline", "deadlines",
        "to-do", "todo", "action item", "deliverable", "deliverables",
        "milestone", "due", "finish", "finished", "complete", "completed",
        "youtube", "video", "reel", "blog post", "article"
    ],
    "calorie_tracker": [
        "ate", "eat", "eating", "food", "foods", "meal", "meals",
        "breakfast", "lunch", "dinner", "snack", "snacks",
        "calories", "calorie", "protein", "carbs", "carbohydrates",
        "fats", "fat", "nutrition", "macro", "macros"
    ],
    "expense_tracker": [
        "spent", "spend", "spending", "bought", "buy", "buying",
        "paid", "pay", "payment", "cost", "costs", "price",
        "expense", "expenses", "subscription", "subscriptions",
        "dollar", "dollars", "$", "money"
    ],
    "blog_content": [
        "blog", "post", "article", "publish", "publishing",
        "draft", "drafts", "writing", "write", "written",
        "kas.blog", "content"
    ],
    "workout_schedule": [
        "workout plan", "gym", "training", "exercise plan",
        "leg day", "push day", "pull day", "cardio"
    ],
    "recipe_collection": [
        "recipe", "recipes", "cook", "cooking", "cooked",
        "ingredients", "how to make"
    ],
    "media_library": [
        "movie", "movies", "show", "shows", "tv", "watch", "watched",
        "watching", "podcast", "podcasts", "listen", "listened"
    ],
}


def detect_databases(text: str) -> Set[str]:
    """
    Detect which databases might be relevant based on keywords in the input.
    
    This is a lightweight pre-filter that runs BEFORE the LLM call.
    It's intentionally broad - false positives are fine, false negatives are not.
    
    Args:
        text: User input text
    
    Returns:
        Set of database names that might be relevant
    """
    text_lower = text.lower()
    detected = set()
    
    for database, keywords in DATABASE_KEYWORDS.items():
        for keyword in keywords:
            # Use word boundary matching for short keywords to avoid false positives
            if len(keyword) <= 3:
                # Short keywords need word boundaries
                if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
                    detected.add(database)
                    break
            else:
                # Longer keywords can use simple containment
                if keyword in text_lower:
                    detected.add(database)
                    break
    
    return detected


# ========================================
# Control Data Structures
# ========================================

@dataclass
class Control:
    """A single control from the ai_controls database."""
    page_id: str
    name: str
    control_type: Optional[str]
    priority: int
    contexts: List[str]
    target_databases: List[str]  # Empty = global control
    content: str  # The actual instruction from page content
    active: bool = True
    url: Optional[str] = None
    
    @property
    def is_global(self) -> bool:
        """Global controls have no target_database set."""
        return len(self.target_databases) == 0
    
    @classmethod
    def from_notion_page(cls, page: Dict[str, Any], content: str) -> "Control":
        """Create Control from Notion page data and fetched content."""
        props = page.get("properties", {})
        
        # Extract title
        name = "Untitled"
        title_prop = props.get("Name", {})
        if title_prop.get("title"):
            name = title_prop["title"][0].get("plain_text", "Untitled")
        
        # Extract control_type
        control_type = None
        type_prop = props.get("control_type", {})
        if type_prop.get("select"):
            control_type = type_prop["select"].get("name")
        
        # Extract priority (default to 50 if not set)
        priority = 50
        priority_prop = props.get("priority", {})
        if priority_prop.get("number") is not None:
            priority = priority_prop["number"]
        
        # Extract contexts (multi_select)
        contexts = []
        context_prop = props.get("context", {})
        if context_prop.get("multi_select"):
            contexts = [c["name"] for c in context_prop["multi_select"]]
        
        # Extract target_databases (multi_select)
        target_databases = []
        target_prop = props.get("target_database", {})
        if target_prop.get("multi_select"):
            target_databases = [db["name"] for db in target_prop["multi_select"]]
        
        # Extract active status
        active = props.get("active", {}).get("checkbox", True)
        
        return cls(
            page_id=page.get("id", ""),
            name=name,
            control_type=control_type,
            priority=priority,
            contexts=contexts,
            target_databases=target_databases,
            content=content,
            active=active,
            url=page.get("url")
        )


@dataclass
class ControlsCache:
    """Cache for loaded controls with TTL support."""
    controls: List[Control] = field(default_factory=list)
    last_fetch: float = 0
    ttl_seconds: int = 300  # 5 minutes default
    
    @property
    def is_stale(self) -> bool:
        """Check if cache needs refresh."""
        return time.time() - self.last_fetch > self.ttl_seconds
    
    @property
    def is_empty(self) -> bool:
        return len(self.controls) == 0
    
    def update(self, controls: List[Control]) -> None:
        """Update cache with new controls."""
        self.controls = controls
        self.last_fetch = time.time()
    
    def clear(self) -> None:
        """Clear the cache."""
        self.controls = []
        self.last_fetch = 0


# ========================================
# Controls Loader
# ========================================

class ControlsLoader:
    """
    Loads and manages AI controls from Notion.
    
    Features:
    - Fetches active controls from ai_controls database
    - Caches controls with configurable TTL
    - Hierarchical loading: global controls always, specific controls when needed
    - Lightweight keyword detection for selective control inclusion
    
    Hierarchy:
        Priority 1-9:   Global controls (Master Router, Word Dump Parser)
        Priority 10+:   Database-specific controls (only when relevant)
    
    Example:
        loader = ControlsLoader(cache_ttl=300)
        await loader.initialize(mcp_client)
        
        # Smart loading based on input
        controls_section = loader.format_for_input("ate eggs for breakfast")
        # → Includes: Master Router, Word Dump Parser, Calorie Tracking Parser
        # → Excludes: Zettelkasten Standards, Habit Tracker Rules, etc.
    """
    
    SOURCE_NAME = "ai_controls"
    
    def __init__(self, cache_ttl: int = 300):
        """
        Initialize the controls loader.

        Args:
            cache_ttl: Cache time-to-live in seconds (default: 5 minutes)
        """
        self._cache = ControlsCache(ttl_seconds=cache_ttl)
        self._initialized = False
        self._refresh_lock: asyncio.Lock = asyncio.Lock()
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized and not self._cache.is_empty
    
    @property
    def controls(self) -> List[Control]:
        """Get all cached controls."""
        return self._cache.controls
    
    @property
    def global_controls(self) -> List[Control]:
        """Get controls that apply to all inputs (no target_database)."""
        return [c for c in self._cache.controls if c.is_global]
    
    @property
    def specific_controls(self) -> List[Control]:
        """Get controls that target specific databases."""
        return [c for c in self._cache.controls if not c.is_global]
    
    async def initialize(self, mcp_client) -> None:
        """
        Initialize by fetching controls from Notion.
        
        Args:
            mcp_client: NotionMCPClient instance (must be connected)
        """
        await self.refresh(mcp_client)
        self._initialized = True
    
    async def refresh(self, mcp_client, force: bool = False) -> None:
        """
        Refresh controls from Notion.

        Uses double-checked locking so concurrent callers only run one refresh.

        Args:
            mcp_client: NotionMCPClient instance
            force: Refresh even if cache is fresh
        """
        # Fast path — cache is fresh
        if not force and not self._cache.is_stale and not self._cache.is_empty:
            return

        async with self._refresh_lock:
            # Re-check inside the lock in case another coroutine already refreshed
            if not force and not self._cache.is_stale and not self._cache.is_empty:
                return

            # Query all active controls
            result = await mcp_client.query_database(
                database_name=self.SOURCE_NAME,
                filter={
                    "property": "active",
                    "checkbox": {"equals": True}
                },
                sorts=[{"property": "priority", "direction": "ascending"}],
                page_size=50
            )

            pages = result.get("results", [])

            # Fetch content for each control
            controls = []
            for page in pages:
                page_id = page.get("id", "")
                try:
                    content_result = await mcp_client.get_page_content(page_id)
                    content = content_result.get("content_markdown", "")
                except Exception:
                    content = ""

                control = Control.from_notion_page(page, content)
                controls.append(control)

            self._cache.update(controls)
    
    # ========================================
    # Filtering Methods
    # ========================================
    
    def get_by_type(self, control_type: ControlType | str) -> List[Control]:
        """Get controls of a specific type."""
        type_str = control_type.value if isinstance(control_type, ControlType) else control_type
        return [c for c in self._cache.controls if c.control_type == type_str]
    
    def get_by_context(self, context: str) -> List[Control]:
        """Get controls matching a specific context."""
        return [c for c in self._cache.controls if context in c.contexts]
    
    def get_by_database(self, database: str) -> List[Control]:
        """Get controls targeting a specific database."""
        return [c for c in self._cache.controls if database in c.target_databases]
    
    def get_controls_for_databases(self, databases: Set[str]) -> List[Control]:
        """
        Get global controls + controls targeting any of the specified databases.
        
        Args:
            databases: Set of database names detected from input
        
        Returns:
            List of relevant controls, sorted by priority
        """
        relevant = []
        
        for control in self._cache.controls:
            # Always include global controls
            if control.is_global:
                relevant.append(control)
                continue
            
            # Include if any target database matches
            if any(db in databases for db in control.target_databases):
                relevant.append(control)
        
        # Already sorted by priority from Notion query, but ensure it
        return sorted(relevant, key=lambda c: c.priority)
    
    # ========================================
    # Formatting Methods
    # ========================================
    
    def format_for_input(self, user_input: str, include_metadata: bool = True) -> str:
        """
        Format controls for a specific user input using keyword detection.
        
        This is the RECOMMENDED method for prompt injection. It:
        1. Detects which databases might be relevant via keywords
        2. Includes global controls (always)
        3. Includes only relevant database-specific controls
        
        Args:
            user_input: The user's natural language input
            include_metadata: Include control type and target info in XML
        
        Returns:
            Formatted string ready for prompt injection
        """
        # Detect relevant databases
        detected = detect_databases(user_input)
        
        # Get relevant controls
        controls = self.get_controls_for_databases(detected)
        
        return self._format_controls(controls, include_metadata, detected)
    
    def format_for_prompt(
        self,
        controls: Optional[List[Control]] = None,
        include_metadata: bool = False
    ) -> str:
        """
        Format controls for system prompt injection.
        
        Args:
            controls: Specific controls to format (uses all cached if None)
            include_metadata: Include control type and target info
        
        Returns:
            Formatted string ready for prompt injection
        """
        controls_to_format = controls or self._cache.controls
        return self._format_controls(controls_to_format, include_metadata)
    
    def format_routing_prompt(self) -> str:
        """
        Get formatted routing-specific controls for the parser.
        DEPRECATED: Use format_for_input() instead for smart loading.
        
        Returns:
            Formatted string with master router + database-specific rules
        """
        # Get routing-related controls
        routing_controls = self.get_by_type(ControlType.ROUTING_LOGIC)
        quality_controls = self.get_by_type(ControlType.QUALITY_CRITERIA)
        template_controls = self.get_by_type(ControlType.PROMPT_TEMPLATE)
        
        # Combine and sort by priority
        all_controls = routing_controls + quality_controls + template_controls
        all_controls.sort(key=lambda c: c.priority)
        
        return self._format_controls(all_controls, include_metadata=True)
    
    def _format_controls(
        self, 
        controls: List[Control], 
        include_metadata: bool = False,
        detected_databases: Optional[Set[str]] = None
    ) -> str:
        """Internal method to format controls as XML."""
        if not controls:
            return ""
        
        sections = ["<agent_controls>"]
        
        # Add detection info if available
        if detected_databases:
            sections.append(f"<!-- Detected databases: {', '.join(sorted(detected_databases))} -->")
            sections.append("")
        
        for control in controls:
            # Skip empty content
            if not control.content.strip():
                continue
            
            # Build control tag
            attrs = [f'name="{control.name}"']
            
            if include_metadata:
                if control.control_type:
                    attrs.append(f'type="{control.control_type}"')
                if control.target_databases:
                    attrs.append(f'targets="{",".join(control.target_databases)}"')
                else:
                    attrs.append('targets="global"')
                attrs.append(f'priority="{control.priority}"')
            
            attr_str = " ".join(attrs)
            
            sections.append(f"<control {attr_str}>")
            sections.append(control.content.strip())
            sections.append("</control>")
            sections.append("")  # Empty line between controls
        
        sections.append("</agent_controls>")
        
        return "\n".join(sections)
    
    def invalidate_cache(self) -> None:
        """Force cache invalidation."""
        self._cache.clear()
    
    # ========================================
    # Debug / Inspection Methods
    # ========================================
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about loaded controls."""
        return {
            "total": len(self.controls),
            "global": len(self.global_controls),
            "specific": len(self.specific_controls),
            "by_type": {
                ct.value: len(self.get_by_type(ct))
                for ct in ControlType
            },
            "cache_age_seconds": int(time.time() - self._cache.last_fetch) if self._cache.last_fetch else None,
            "cache_ttl_seconds": self._cache.ttl_seconds,
        }
    
    def preview_for_input(self, user_input: str) -> Dict[str, Any]:
        """
        Preview which controls would be included for a given input.
        Useful for debugging.
        
        Args:
            user_input: The user's natural language input
        
        Returns:
            Dict with detection results and control names
        """
        detected = detect_databases(user_input)
        controls = self.get_controls_for_databases(detected)
        
        return {
            "input": user_input,
            "detected_databases": sorted(detected),
            "controls_included": [
                {
                    "name": c.name,
                    "type": c.control_type,
                    "priority": c.priority,
                    "is_global": c.is_global,
                    "targets": c.target_databases,
                }
                for c in controls
            ],
            "controls_excluded": [
                {
                    "name": c.name,
                    "targets": c.target_databases,
                }
                for c in self._cache.controls
                if c not in controls
            ],
            "total_chars": len(self.format_for_input(user_input)),
        }


# ========================================
# Module-level singleton
# ========================================

_controls_loader: Optional[ControlsLoader] = None


def get_controls_loader(cache_ttl: int = 300) -> ControlsLoader:
    """
    Get or create the global ControlsLoader instance.
    
    Args:
        cache_ttl: Cache TTL in seconds (only used on first call)
    
    Returns:
        ControlsLoader singleton
    """
    global _controls_loader
    if _controls_loader is None:
        _controls_loader = ControlsLoader(cache_ttl=cache_ttl)
    return _controls_loader


async def initialize_controls(mcp_client, cache_ttl: int = 300) -> ControlsLoader:
    """
    Initialize the global controls loader.
    
    Args:
        mcp_client: NotionMCPClient instance
        cache_ttl: Cache TTL in seconds
    
    Returns:
        Initialized ControlsLoader
    """
    loader = get_controls_loader(cache_ttl)
    await loader.initialize(mcp_client)
    return loader


# ========================================
# Example Usage
# ========================================

async def main():
    """Example usage of the controls loader with hierarchical loading."""
    from rich import print as rprint
    from rich.panel import Panel
    from rich.table import Table
    
    from src.notion_assistant.clients.mcp_client import NotionMCPClient
    
    rprint("[bold cyan]═══ AI Controls Loader Demo (Hierarchical) ═══[/bold cyan]\n")
    
    async with NotionMCPClient() as mcp:
        # Initialize controls
        loader = await initialize_controls(mcp)
        
        # Show stats
        stats = loader.get_stats()
        rprint(f"[green]✓ Loaded {stats['total']} controls[/green]")
        rprint(f"  • Global: {stats['global']}")
        rprint(f"  • Database-specific: {stats['specific']}\n")
        
        # Show all controls
        table = Table(title="All Controls", show_header=True)
        table.add_column("Priority")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Targets")
        table.add_column("Chars")
        
        for control in loader.controls:
            table.add_row(
                str(control.priority),
                control.name,
                control.control_type or "-",
                ", ".join(control.target_databases) if control.target_databases else "[global]",
                str(len(control.content))
            )
        
        rprint(table)
        rprint()
        
        # Test hierarchical loading
        test_inputs = [
            "Create a note about FastMCP",
            "Ate eggs for breakfast, about 200 calories",
            "Did my workout and had an idea about webhooks",
            "Spent $50 on lunch and finished the deployment task",
        ]
        
        rprint("[bold cyan]═══ Hierarchical Loading Test ═══[/bold cyan]\n")
        
        for user_input in test_inputs:
            preview = loader.preview_for_input(user_input)
            
            rprint(f"[yellow]Input:[/yellow] {user_input}")
            rprint(f"[dim]Detected: {', '.join(preview['detected_databases']) or 'none'}[/dim]")
            rprint(f"[green]Included ({len(preview['controls_included'])}):[/green] {', '.join(c['name'] for c in preview['controls_included'])}")
            rprint(f"[red]Excluded ({len(preview['controls_excluded'])}):[/red] {', '.join(c['name'] for c in preview['controls_excluded'])}")
            rprint(f"[dim]Prompt size: {preview['total_chars']} chars[/dim]")
            rprint()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
