"""
State an Models for the Notion Assistant Agent
"""
from typing import TypedDict, Annotated, Dict, Any, List, Optional

class IntentResult(TypedDict):
    """Result of executing a single intent."""
    intent: Dict[str, Any]
    result: Dict[str, Any]
    success: bool
    error: Optional[str]


class AgentState(TypedDict):
    """State that flows through the LangGraph workflow."""
    
    # User input
    user_input: str
    
    # Parsed intents (multiple from single input)
    parsed: Dict[str, Any]  # ParsedInput as dict
    
    # Router decision
    execution_plan: List[Dict[str, Any]]  # Which intents to execute and how
    
    # Results from all intent executions
    intent_results: List[IntentResult]
    
    # Final response to user
    response: str
    
    # Error tracking
    error: Optional[str]