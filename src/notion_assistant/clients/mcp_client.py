"""
FastMCP Client Integration
Provides a clean interface for LangGraph agents to interact with the Notion MCP server.
Supports multiple transport types: STDIO (local), HTTP (remote), and SSE (legacy).
"""
import os
from typing import Dict, Any, Optional, List
from pathlib import Path
from dotenv import load_dotenv

# Import FastMCP client
try:
    from fastmcp import Client
    from fastmcp.client.transports import (
        PythonStdioTransport,
        StreamableHttpTransport,
        SSETransport,
    )
except ImportError:
    raise ImportError(
        "fastmcp not installed. Run: uv add fastmcp>=3.0.0"
    )

# Optional: Bearer auth for authenticated remote servers
try:
    from fastmcp.client.auth import BearerAuth
except ImportError:
    BearerAuth = None

load_dotenv()


class NotionMCPClient:
    """
    Wrapper around FastMCP Client for Notion operations.
    
    Supports multiple transport types:
    - "stdio": Local Python script via subprocess (development)
    - "http": Remote server via Streamable HTTP (production)
    - "sse": Remote server via SSE (legacy, for older deployments)
    - "auto": Auto-detect from URL/path (recommended)
    
    Environment Variables:
    - NOTION_MCP_URL: Remote server URL (for http/sse transport)
    - NOTION_MCP_PATH: Local script path (for stdio transport)
    - NOTION_MCP_TOKEN: Bearer token for authenticated servers
    - NOTION_MCP_TRANSPORT: Transport type override ("stdio", "http", "sse")
    
    Usage:
        # Auto-detect from environment
        async with NotionMCPClient() as client:
            result = await client.query_database("zettelkasten")
        
        # Explicit remote connection
        async with NotionMCPClient(
            url="https://my-server.com/mcp",
            transport="http"
        ) as client:
            result = await client.list_databases()
        
        # Local development
        async with NotionMCPClient(
            path="/path/to/main.py",
            transport="stdio"
        ) as client:
            result = await client.create_page(...)
    """
    
    def __init__(
        self,
        url: Optional[str] = None,
        path: Optional[str] = None,
        transport: str = "auto",
        token: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the MCP client.
        
        Args:
            url: Remote server URL (for http/sse transport)
            path: Local script path (for stdio transport)
            transport: Transport type - "auto", "stdio", "http", or "sse"
            token: Bearer token for authenticated servers
            headers: Additional headers for HTTP requests
        """
        # Get configuration from environment or parameters
        self.url = url or os.getenv("NOTION_MCP_URL")
        self.path = path or os.getenv("NOTION_MCP_PATH")
        self.token = token or os.getenv("NOTION_MCP_TOKEN")
        self.transport_type = transport if transport != "auto" else os.getenv("NOTION_MCP_TRANSPORT", "auto")
        self.headers = headers or {}
        
        # Add token to headers if provided
        if self.token and "Authorization" not in self.headers:
            self.headers["Authorization"] = f"Bearer {self.token}"
        
        self._client: Optional[Client] = None
        self._transport = None
    
    def _resolve_transport(self):
        """Determine the appropriate transport based on configuration."""
        
        # If explicit transport type specified (not auto)
        if self.transport_type == "stdio":
            return self._create_stdio_transport()
        elif self.transport_type == "http":
            return self._create_http_transport()
        elif self.transport_type == "sse":
            return self._create_sse_transport()
        
        # Auto-detect: prefer URL if available, fall back to path
        if self.url:
            # URL ending in /sse uses SSE transport, otherwise HTTP
            if self.url.rstrip("/").endswith("/sse"):
                return self._create_sse_transport()
            else:
                return self._create_http_transport()
        elif self.path:
            return self._create_stdio_transport()
        else:
            # Last resort: try default local path
            default_path = self._get_default_path()
            if default_path and Path(default_path).exists():
                self.path = default_path
                return self._create_stdio_transport()
            
            raise ValueError(
                "No MCP server configuration found. Set one of:\n"
                "  - NOTION_MCP_URL: Remote server URL\n"
                "  - NOTION_MCP_PATH: Local script path\n"
                "  - Or pass url= or path= to NotionMCPClient()"
            )
    
    def _get_default_path(self) -> Optional[str]:
        """Get default local MCP server path."""
        # Try relative to this file
        candidates = [
            Path(__file__).parent.parent.parent.parent / "kas-fastmcp" / "main.py",
            Path.home() / "Projects" / "kas-fastmcp" / "main.py",
            Path.cwd() / "kas-fastmcp" / "main.py",
        ]
        
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return None
    
    def _create_stdio_transport(self):
        """Create STDIO transport for local Python script."""
        if not self.path:
            raise ValueError("STDIO transport requires path to Python script")
        
        path = Path(self.path)
        if not path.exists():
            raise FileNotFoundError(f"MCP server script not found: {self.path}")
        
        return PythonStdioTransport(
            script_path=path,
            # Optionally pass environment variables
            env={
                **os.environ,
                # Ensure child process inherits necessary env vars
            }
        )
    
    def _create_http_transport(self):
        """Create Streamable HTTP transport for remote server."""
        if not self.url:
            raise ValueError("HTTP transport requires server URL")
        
        return StreamableHttpTransport(
            url=self.url,
            headers=self.headers if self.headers else None,
        )
    
    def _create_sse_transport(self):
        """Create SSE transport for legacy remote server."""
        if not self.url:
            raise ValueError("SSE transport requires server URL")
        
        return SSETransport(
            url=self.url,
            headers=self.headers if self.headers else None,
        )
    
    async def __aenter__(self):
        """Async context manager entry - establishes connection."""
        self._transport = self._resolve_transport()
        self._client = Client(self._transport)
        await self._client.__aenter__()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - closes connection."""
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)
    
    @property
    def is_remote(self) -> bool:
        """Check if using remote transport."""
        return self.transport_type in ("http", "sse") or (
            self.transport_type == "auto" and self.url is not None
        )
    
    @property
    def connection_info(self) -> str:
        """Get human-readable connection info."""
        if self.url:
            return f"Remote: {self.url}"
        elif self.path:
            return f"Local: {self.path}"
        return "Unknown"
    
    # ========================================
    # Query Operations
    # ========================================
    
    async def query_database(
        self,
        database_name: str,
        filter: Optional[Dict[str, Any]] = None,
        sorts: Optional[List[Dict[str, Any]]] = None,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        Query a Notion database.
        
        Args:
            database_name: Name from databases.yaml (e.g., "zettelkasten")
            filter: Notion filter object
            sorts: Notion sorts array
            page_size: Number of results (1-100)
        
        Returns:
            Query results with pages array
        """
        tool_args = {
            "source_name": database_name,
            "filter": filter,
            "sorts": sorts,
            "page_size": page_size
        }
        tool_args = {k: v for k, v in tool_args.items() if v is not None}
        
        call_result = await self._client.call_tool("notion_query", tool_args)
        return call_result.data
    
    async def search(
        self,
        query: str,
        filter: Optional[Dict[str, Any]] = None,
        page_size: int = 10
    ) -> Dict[str, Any]:
        """
        Search across workspace.
        
        Args:
            query: Search query string
            filter: Optional filter (e.g., {"property": "object", "value": "page"})
            page_size: Number of results
        
        Returns:
            Search results
        """
        tool_args = {
            "query": query,
            "filter": filter,
            "page_size": page_size
        }
        tool_args = {k: v for k, v in tool_args.items() if v is not None}
        call_result = await self._client.call_tool("notion_search", tool_args)
        return call_result.data
    
    async def find_page_by_name(
        self,
        database_name: str,
        page_name: str,
        title_property: str = "title"
    ) -> Dict[str, Any]:
        """
        Find a page by exact title match.
        
        Args:
            database_name: Database to search
            page_name: Exact page title
            title_property: Name of title property (default: "title")
        
        Returns:
            Page data or {"found": False}
        """
        tool_args = {
            "source_name": database_name,
            "page_name": page_name,
            "title_property": title_property,
        }
        call_result = await self._client.call_tool("notion_find_page_by_name", tool_args)
        return call_result.data
    
    # ========================================
    # Create Operations
    # ========================================
    
    async def create_page(
        self,
        database_name: str,
        properties: Dict[str, Any],
        content_markdown: Optional[str] = None,
        parent_page_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new page in a database.
        
        Args:
            database_name: Database to create page in
            properties: Page properties in Notion format
            content_markdown: Optional markdown content for page body
            parent_page_id: Optional parent page (for nested pages)
        
        Returns:
            Created page data
        """
        tool_args = {
            "source_name": database_name,
            "properties": properties,
            "content_markdown": content_markdown,
            "parent_page_id": parent_page_id,
        }
        tool_args = {k: v for k, v in tool_args.items() if v is not None}
        call_result = await self._client.call_tool("notion_create_item", tool_args)
        return call_result.data
    
    # ========================================
    # Read Operations
    # ========================================
    
    async def get_page(
        self,
        page_id: str,
        include_content: bool = False
    ) -> Dict[str, Any]:
        """
        Get a page by ID.
        
        Args:
            page_id: Notion page ID
            include_content: Whether to include page content as markdown
        
        Returns:
            Page data
        """
        tool_args = {
            "page_id": page_id,
            "include_content": include_content
        }
        call_result = await self._client.call_tool("notion_get_page", tool_args)
        return call_result.data
    
    async def get_page_content(
        self,
        page_id: str
    ) -> Dict[str, Any]:
        """
        Get page content as markdown.
        
        Args:
            page_id: Notion page ID
        
        Returns:
            Object with page_id, title, content (markdown), and url
        """
        tool_args = {"page_id": page_id}
        call_result = await self._client.call_tool("notion_get_page_content", tool_args)
        return call_result.data
    
    # ========================================
    # Update Operations
    # ========================================
    
    async def update_page(
        self,
        page_id: str,
        properties: Optional[Dict[str, Any]] = None,
        archived: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Update a page's properties.
        
        Args:
            page_id: Page to update
            properties: Properties to update (partial update supported)
            archived: Archive or restore the page
        
        Returns:
            Updated page data
        """
        tool_args = {
            "page_id": page_id,
            "properties": properties,
            "archived": archived,
        }
        tool_args = {k: v for k, v in tool_args.items() if v is not None}
        call_result = await self._client.call_tool("notion_update_item", tool_args)
        return call_result.data
    
    async def append_content(
        self,
        page_id: str,
        content_markdown: str
    ) -> Dict[str, Any]:
        """
        Append content to a page.
        
        Args:
            page_id: Page to append to
            content_markdown: Markdown content to append
        
        Returns:
            Confirmation with page_id and blocks_added count
        """
        tool_args = {
            "page_id": page_id,
            "content_markdown": content_markdown
        }
        call_result = await self._client.call_tool("notion_append_content", tool_args)
        return call_result.data
    
    # ========================================
    # Discovery Operations
    # ========================================
    
    async def list_databases(self) -> Dict[str, Any]:
        """
        List all configured databases by validating each against the Notion workspace.

        Uses the notion_validate_config tool which iterates every database name
        registered in the MCP server's config and returns their IDs, titles and URLs.

        Returns:
            Dict with a "data_sources" list, each entry containing:
              id, name (config key), title, url
        """
        call_result = await self._client.call_tool("notion_validate_config", {})
        raw = call_result.data  # {"results": {name: {...}}, ...}

        data_sources = []
        for config_name, info in raw.get("results", {}).items():
            if info.get("status") == "valid":
                data_sources.append({
                    "id": info.get("data_source_id", ""),
                    "name": config_name,
                    "title": info.get("title", config_name),
                    "url": info.get("url", ""),
                })

        return {"data_sources": data_sources}
    
    async def list_data_sources(
        self,
        database_name: str
    ) -> Dict[str, Any]:
        """
        List data sources for a database.
        
        Args:
            database_name: Database name from config
        
        Returns:
            List of data sources with IDs and names
        """
        tool_args = {"source_name": database_name}
        call_result = await self._client.call_tool("notion_list_data_sources", tool_args)
        return call_result.data
    
    async def get_data_source_schema(
        self,
        database_name: str
    ) -> Dict[str, Any]:
        """
        Get database schema (properties and types).
        
        Args:
            database_name: Database name from config
        
        Returns:
            Schema details including properties with types and options
        """
        tool_args = {"source_name": database_name}
        call_result = await self._client.call_tool("notion_get_data_source", tool_args)
        return call_result.data


# ========================================
# Factory Functions
# ========================================

def create_client(
    url: Optional[str] = None,
    path: Optional[str] = None,
    transport: str = "auto",
    token: Optional[str] = None,
) -> NotionMCPClient:
    """
    Factory function to create a NotionMCPClient.
    
    Reads configuration from environment variables if not provided.
    
    Args:
        url: Remote server URL
        path: Local script path  
        transport: Transport type ("auto", "stdio", "http", "sse")
        token: Bearer token for authenticated servers
    
    Returns:
        Configured NotionMCPClient instance
    """
    return NotionMCPClient(
        url=url,
        path=path,
        transport=transport,
        token=token,
    )


# ========================================
# Helper Functions for Common Patterns
# ========================================

async def create_simple_note(
    title: str,
    content: str,
    database: str = "zettelkasten",
    tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Convenience function to create a simple note.
    
    Args:
        title: Note title
        content: Note content (markdown)
        database: Database name
        tags: Optional tags
    
    Returns:
        Created page data
    """
    properties = {
        "title": {
            "title": [{"text": {"content": title}}]
        }
    }
    
    if tags:
        properties["tags"] = {
            "multi_select": [{"name": tag} for tag in tags]
        }
    
    async with NotionMCPClient() as client:
        return await client.create_page(
            database_name=database,
            properties=properties,
            content_markdown=content
        )


async def search_notes(
    query: str,
    database: Optional[str] = None,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Search for notes across workspace or specific database.
    
    Args:
        query: Search query
        database: Optional database to search
        limit: Max results
    
    Returns:
        List of matching pages
    """
    async with NotionMCPClient() as client:
        if database:
            result = await client.query_database(
                database_name=database,
                page_size=limit
            )
        else:
            result = await client.search(
                query=query,
                page_size=limit
            )
        
        return result.get("results", [])
