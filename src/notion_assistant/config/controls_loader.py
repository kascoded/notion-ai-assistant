"""
AI Controls Loader

Fetches agent instructions from the ai_controls Notion database and injects
them into the parser's system prompt. This enables no-code modifications to
agent behavior - just edit Notion, no redeploy needed.

Architecture:
    Notion ai_controls DB → ControlsLoader → System Prompt Injection → Parser

Usage:
    loader = ControlsLoader()
    await loader.initialize(mcp_client)
    
    # Get all active controls formatted for injection
    prompt_section = await loader.get_controls_prompt()
    
    # Get controls filtered by type
    routing_rules = await loader.get_controls_by_type("routing_logic")
"""
import time
from typing import Dict, Any, List, Optional
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


@dataclass
class Control:
    """A single control from the ai_controls database."""
    page_id: str
    name: str
    control_type: Optional[str]
    priority: int
    contexts: List[str]
    target_databases: List[str]
    content: str  # The actual instruction from page content
    active: bool = True
    url: Optional[str] = None
    
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


class ControlsLoader:
    """
    Loads and manages AI controls from Notion.
    
    Features:
    - Fetches active controls from ai_controls database
    - Caches controls with configurable TTL
    - Filters by control_type, context, or target_database
    - Formats controls for system prompt injection
    
    Example:
        loader = ControlsLoader(cache_ttl=300)
        await loader.initialize(mcp_client)
        
        # Inject into parser prompt
        controls_section = loader.format_for_prompt()
        
        # Or get specific control types
        routing_rules = loader.get_by_type(ControlType.ROUTING_LOGIC)
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
    
    @property
    def is_initialized(self) -> bool:
        return self._initialized and not self._cache.is_empty
    
    @property
    def controls(self) -> List[Control]:
        """Get all cached controls."""
        return self._cache.controls
    
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
        
        Args:
            mcp_client: NotionMCPClient instance
            force: Refresh even if cache is fresh
        """
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
            
            # Fetch page content (the actual instructions)
            try:
                content_result = await mcp_client.get_page_content(page_id)
                content = content_result.get("content_markdown", "")
            except Exception:
                content = ""
            
            control = Control.from_notion_page(page, content)
            controls.append(control)
        
        self._cache.update(controls)
    
    def get_by_type(self, control_type: ControlType | str) -> List[Control]:
        """
        Get controls of a specific type.
        
        Args:
            control_type: Control type to filter by
        
        Returns:
            List of matching controls, sorted by priority
        """
        type_str = control_type.value if isinstance(control_type, ControlType) else control_type
        return [c for c in self._cache.controls if c.control_type == type_str]
    
    def get_by_context(self, context: str) -> List[Control]:
        """
        Get controls matching a specific context.
        
        Args:
            context: Context tag to filter by
        
        Returns:
            List of matching controls
        """
        return [c for c in self._cache.controls if context in c.contexts]
    
    def get_by_database(self, database: str) -> List[Control]:
        """
        Get controls targeting a specific database.
        
        Args:
            database: Database name to filter by
        
        Returns:
            List of matching controls
        """
        return [c for c in self._cache.controls if database in c.target_databases]
    
    def get_relevant_controls(
        self,
        contexts: Optional[List[str]] = None,
        databases: Optional[List[str]] = None,
        control_types: Optional[List[str]] = None
    ) -> List[Control]:
        """
        Get controls matching any of the given filters.
        
        Args:
            contexts: List of context tags to match
            databases: List of target databases to match
            control_types: List of control types to match
        
        Returns:
            List of matching controls, deduplicated and sorted by priority
        """
        matched = set()
        results = []
        
        for control in self._cache.controls:
            # Skip if already matched
            if control.page_id in matched:
                continue
            
            # Check contexts
            if contexts and any(ctx in control.contexts for ctx in contexts):
                matched.add(control.page_id)
                results.append(control)
                continue
            
            # Check databases
            if databases and any(db in control.target_databases for db in databases):
                matched.add(control.page_id)
                results.append(control)
                continue
            
            # Check control types
            if control_types and control.control_type in control_types:
                matched.add(control.page_id)
                results.append(control)
                continue
        
        # Sort by priority
        return sorted(results, key=lambda c: c.priority)
    
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
        
        if not controls_to_format:
            return ""
        
        sections = ["<agent_controls>"]
        
        for control in controls_to_format:
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
                attrs.append(f'priority="{control.priority}"')
            
            attr_str = " ".join(attrs)
            
            sections.append(f"<control {attr_str}>")
            sections.append(control.content.strip())
            sections.append("</control>")
            sections.append("")  # Empty line between controls
        
        sections.append("</agent_controls>")
        
        return "\n".join(sections)
    
    def format_routing_prompt(self) -> str:
        """
        Get formatted routing-specific controls for the parser.
        
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
        
        return self.format_for_prompt(all_controls, include_metadata=True)
    
    def invalidate_cache(self) -> None:
        """Force cache invalidation."""
        self._cache.clear()


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
    """Example usage of the controls loader."""
    from rich import print as rprint
    from rich.panel import Panel
    
    from src.notion_assistant.clients.mcp_client import NotionMCPClient
    
    rprint("[bold cyan]═══ AI Controls Loader Demo ═══[/bold cyan]\n")
    
    async with NotionMCPClient() as mcp:
        # Initialize controls
        loader = await initialize_controls(mcp)
        
        rprint(f"[green]✓ Loaded {len(loader.controls)} active controls[/green]\n")
        
        # Show all controls
        for control in loader.controls:
            rprint(f"[bold]{control.name}[/bold]")
            rprint(f"  Type: {control.control_type}")
            rprint(f"  Priority: {control.priority}")
            rprint(f"  Contexts: {', '.join(control.contexts) or 'none'}")
            rprint(f"  Targets: {', '.join(control.target_databases) or 'all'}")
            rprint(f"  Content: {len(control.content)} chars")
            rprint()
        
        # Show formatted prompt section
        prompt_section = loader.format_routing_prompt()
        
        rprint(Panel(
            prompt_section[:2000] + "..." if len(prompt_section) > 2000 else prompt_section,
            title="Formatted for Prompt Injection",
            border_style="cyan"
        ))


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
