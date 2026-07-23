"""LangGraph workflow state for DecisionTree session navigation.

Separated from core graph models for single responsibility.
These TypedDict states are used by LangGraph workflows for session navigation.

Supports both question nodes and conclusion nodes.
"""

from typing import NotRequired, TypedDict

from smeme.core.models import DecisionTreeSession
from smeme.decision_tree.models import DTGraph


class DecisionTreeSessionState(TypedDict):
    """
    LangGraph workflow state for DecisionTree session navigation.

    Used by the viewer/session workflow to track user progress
    through a questionnaire.

    Each node returns only the fields it modifies, and LangGraph merges them.

    Supports both question nodes and conclusion nodes:
    - Questions: gather information, have outgoing edges
    - Conclusions: terminal outcomes, no outgoing edges
    """

    # Core identifiers
    decision_tree_id: str
    user_id: str
    session: DecisionTreeSession

    # Graph data (loaded once, cached)
    graph: NotRequired[DTGraph]

    # Navigation state
    current_node_id: NotRequired[str | None]
    next_question_id: NotRequired[str | None]  # Actually next node ID (question or conclusion)
    navigation_intent: NotRequired[str | None]  # "next", "previous", "skip", "finish", "review"
    is_conclusion: NotRequired[bool]  # True if next_question_id is a conclusion node

    # Completion state
    is_complete: NotRequired[bool]
    completed_at: NotRequired[str | None]  # ISO timestamp

    # UI messages
    navigation_warning: NotRequired[str | None]
    error_message: NotRequired[str | None]

    # Rendered output
    rendered_output: NotRequired[str]


class SessionStateUpdate(TypedDict, total=False):
    """
    Type hint for partial state updates returned by session workflow nodes.
    All fields are optional since nodes only return what they modify.
    """

    graph: DTGraph
    current_node_id: str | None
    next_question_id: str | None
    navigation_intent: str | None
    is_conclusion: bool  # True if next_question_id is a conclusion node
    is_complete: bool
    completed_at: str | None
    navigation_warning: str | None
    error_message: str | None
    rendered_output: str
