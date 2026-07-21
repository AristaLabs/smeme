"""Editor-specific models for QNR graph modification.

These models define the state and operations for the Editor Workflow.
"""

import inspect
from typing import Any, Literal, NotRequired, TypedDict
from uuid import UUID

from fastapi import Form
from pydantic import BaseModel, Field

from smeme.qnr.models import QNRGraph

# =============================================================================
# Helper Decorator for Form Data Support
# =============================================================================


def as_form(cls: type[BaseModel]) -> type[BaseModel]:
    """
    Decorator to make a Pydantic model compatible with FastAPI Form data.

    Based on: https://github.com/tiangolo/fastapi/issues/2387#issuecomment-731662551
    """
    new_parameters = []

    for field_name, model_field in cls.model_fields.items():
        # Extract the field's annotation
        annotation = model_field.annotation

        # Determine the default value for the Form parameter
        if model_field.is_required():
            default = Form(...)
        elif model_field.default is not None:
            default = Form(model_field.default)
        elif model_field.default_factory is not None:
            default = Form(default_factory=model_field.default_factory)
        else:
            default = Form(None)

        new_parameters.append(
            inspect.Parameter(
                field_name,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=annotation,
            )
        )

    # Update the signature
    cls.__signature__ = inspect.Signature(new_parameters)
    return cls


# =============================================================================
# Editor Workflow State (TypedDict for LangGraph)
# =============================================================================


class QNREditorState(TypedDict):
    """
    LangGraph state for Editor Workflow.

    The Editor Workflow handles write operations and is NOT cached.
    """

    # Input
    qnr_id: UUID
    user_id: UUID
    operation: str  # create_node, create_node_wired, update_node, delete_node, create_edge, etc.
    operation_data: dict  # Operation-specific data

    # Loaded data (always fresh from DB, no cache)
    graph: NotRequired[QNRGraph]
    qnr_title: NotRequired[str]
    is_public: NotRequired[bool]

    # Validation results (from lenient validation)
    is_valid: NotRequired[bool]
    errors: NotRequired[list[str]]  # Blocking errors
    warnings: NotRequired[list[str]]  # Non-blocking warnings

    # Success/error state
    success: NotRequired[bool]
    error_message: NotRequired[str | None]


# =============================================================================
# Request Models for CRUD Operations
# =============================================================================


@as_form
class CreateNodeRequest(BaseModel):
    """
    Request to create a new **question** node (no edges in this step).

    **Single-entry graph:** the first question on an empty graph is the entry.
    Adding another detached question would create a second entry; use
    ``POST /qnr/editor/create_node_wired`` for non-empty graphs instead.

    **Node id:** leave ``node_id`` blank for an opaque server id (``q_<hex>``);
    optional explicit id must be unique and is a stable technical key, not display order.
    """

    qnr_id: UUID = Field(description="QNR ID")
    node_id: str = Field(
        default="",
        description="New node ID; server autogenerates a unique id when blank",
    )
    panel_context_node_id: str = Field(
        default="",
        description="Current editor selection; used only to restore the side panel on errors",
    )
    text: str = Field(description="Question text")
    type: Literal["radio"] = Field(default="radio", description="Question type (radio only)")
    options: str | None = Field(default=None, description="Options (newline-separated)")
    help_text: str | None = Field(default=None, description="Optional help text")
    required: str = Field(
        default="true", description="Whether answer is required (string from form)"
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Convert options string to list and rename fields for operation."""
        data = super().model_dump(**kwargs)
        # Rename fields to match operation expectations
        if "text" in data:
            data["question_text"] = data.pop("text")
        if "type" in data:
            data["question_type"] = data.pop("type")
        # Convert newline-separated string to list
        if data.get("options") and isinstance(data["options"], str):
            data["options"] = [opt.strip() for opt in data["options"].split("\n") if opt.strip()]
        # Convert required string to boolean
        if "required" in data:
            data["required"] = data["required"].lower() in ("true", "1", "yes")
        return data


@as_form
class CreateNodeWiredRequest(BaseModel):
    """Create a question or conclusion plus required edges (single save)."""

    qnr_id: UUID = Field(description="QNR ID")
    panel_context_node_id: str = Field(
        default="",
        description="Current editor selection; used only to restore the side panel on errors",
    )
    kind: Literal["question", "conclusion"] = Field(description="Node type to add")
    node_id: str = Field(
        default="",
        description="Explicit id, or blank for server-generated opaque id",
    )

    # Question fields
    text: str = Field(default="", description="Question text")
    type: Literal["radio"] = Field(default="radio", description="Question type (radio only)")
    options: str | None = Field(default=None, description="Options (newline-separated) for radio")
    help_text: str | None = Field(default=None, description="Optional help text")
    required: str = Field(default="true", description="Whether answer is required (form string)")
    question_wiring: str = Field(
        default="",
        description="incoming | new_start (ignored when graph is empty — first question)",
    )
    predecessor_ids: str = Field(
        default="",
        description="Comma-separated question ids for incoming wiring",
    )
    incoming_edge_condition: str | None = Field(
        default=None,
        description="Optional shared condition for each predecessor→new edge",
    )

    # Conclusion fields
    title: str = Field(default="", description="Conclusion title")
    summary: str = Field(default="", description="Conclusion summary")
    recommendations: str | None = Field(
        default=None, description="Recommendations (newline-separated)"
    )
    severity: Literal["info", "warning", "critical"] = Field(default="info")
    conclusion_source: str = Field(
        default="", description="Source question id for first incoming edge"
    )
    conclusion_condition: str = Field(
        default="", description="Condition for edge into conclusion (required)"
    )
    conclusion_edges_json: str = Field(
        default="",
        description='Optional JSON list of {"source":"…","condition":"…"} overriding single fields',
    )


@as_form
class UpdateNodeRequest(BaseModel):
    """Request to update an existing node (supports both question and conclusion nodes)."""

    qnr_id: UUID = Field(description="QNR ID")
    node_id: str = Field(description="Node ID to update")

    # Question node fields
    text: str | None = Field(default=None, description="Updated question text")
    type: Literal["radio"] | None = Field(
        default=None, description="Updated question type (radio only)"
    )
    options: str | None = Field(default=None, description="Updated options (newline-separated)")
    help_text: str | None = Field(default=None, description="Updated help text")
    required: str | None = Field(
        default=None, description="Whether answer is required (string from form)"
    )

    # Conclusion node fields
    title: str | None = Field(default=None, description="Updated conclusion title")
    summary: str | None = Field(default=None, description="Updated conclusion summary")
    recommendations: str | None = Field(
        default=None, description="Updated recommendations (newline-separated)"
    )
    severity: Literal["info", "warning", "critical"] | None = Field(
        default=None, description="Updated severity level"
    )

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        """Convert form data and prepare for operation."""
        # Handle exclude parameters for Pydantic v2
        exclude_none = kwargs.pop("exclude_none", True)  # Default to True
        exclude = kwargs.pop("exclude", set())

        if isinstance(exclude, dict):
            exclude = set(exclude.keys())
        elif not isinstance(exclude, set):
            exclude = set(exclude) if exclude else set()

        # Always exclude None values and the specified fields
        data = super().model_dump(exclude_none=exclude_none, exclude=exclude, **kwargs)

        # Handle question fields
        if "text" in data:
            data["question_text"] = data.pop("text")
        if "type" in data:
            data["question_type"] = data.pop("type")
        # Convert newline-separated string to list for options
        if isinstance(data.get("options"), str):
            options_list = [opt.strip() for opt in data["options"].split("\n") if opt.strip()]
            data["options"] = options_list if options_list else None
        # Convert required string to boolean
        if "required" in data:
            data["required"] = data["required"].lower() in ("true", "1", "yes")

        # Handle conclusion fields
        # Convert newline-separated string to list for recommendations
        if data.get("recommendations") and isinstance(data["recommendations"], str):
            data["recommendations"] = [
                rec.strip() for rec in data["recommendations"].split("\n") if rec.strip()
            ]

        return data


@as_form
class DeleteNodeRequest(BaseModel):
    """Request to delete a node."""

    qnr_id: UUID = Field(description="QNR ID")
    node_id: str = Field(description="Node ID to delete")


@as_form
class CreateEdgeRequest(BaseModel):
    """Request to create a new edge."""

    qnr_id: UUID = Field(description="QNR ID")
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    condition: str | None = Field(default=None, description="Optional condition")


@as_form
class UpdateEdgeRequest(BaseModel):
    """Request to update an existing edge."""

    qnr_id: UUID = Field(description="QNR ID")
    source: str = Field(description="Source node ID")
    old_target: str = Field(description="Current target node ID")
    old_condition: str | None = Field(default=None, description="Current condition")
    new_target: str | None = Field(default=None, description="New target node ID")
    new_condition: str | None = Field(default=None, description="Updated condition")


@as_form
class DeleteEdgeRequest(BaseModel):
    """Request to delete an edge."""

    qnr_id: UUID = Field(description="QNR ID")
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    condition: str | None = Field(default=None, description="Optional condition")
