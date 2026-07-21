"""Pydantic models for the generation brief (Section 1).

Validated at form submit. Maps to initial workflow state.
Field names must match form input names exactly for FastAPI Form() binding.
"""

from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from smeme.qnr.generation.agentic.validation import parse_and_validate_include_urls


class GenerationBriefInput(BaseModel):
    """Input for the guided brief form (POST /qnr/agentic/generate).

    Required: title, user_prompt (goal).
    Optional: enable_user_materials, enable_web_search, country, include_domains,
    exclude_domains, pasted_text.
    """

    model_config = {"extra": "forbid"}

    title: str = Field(
        ...,
        min_length=3,
        max_length=200,
        description="User-provided QNR name",
    )
    user_prompt: str = Field(
        ...,
        min_length=20,
        max_length=400,
        description="Research goal; used as Tavily query when web search is enabled",
    )
    enable_user_materials: bool = Field(
        default=False,
        description="When true, include pasted text and/or uploaded files in research context",
    )
    enable_web_search: bool = Field(
        default=False,
        description="When true, run Tavily web search (optional URL extract or broad search)",
    )
    country: str = Field(default="")
    include_domains: str = Field(
        default="",
        description="URLs: one per line or comma-separated; validated when web search enabled",
    )
    exclude_domains: str = Field(default="")
    pasted_text: str = Field(default="")
    user_conclusions: str = Field(default="")
    confirm_goal_only: bool = Field(
        default=False,
        description="User confirmed proceeding with goal text only (no web search or materials)",
    )

    @field_validator(
        "enable_user_materials", "enable_web_search", "confirm_goal_only", mode="before"
    )
    @classmethod
    def coerce_checkbox(cls, v: str | bool) -> bool:
        """Form checkboxes send 'on' when checked; absent when unchecked."""
        if isinstance(v, bool):
            return v
        return str(v).lower() in ("on", "true", "1", "yes")

    @field_validator("pasted_text")
    @classmethod
    def cap_pasted_text(cls, v: str) -> str:
        return v[:50000]

    @model_validator(mode="after")
    def validate_opt_in_sections(self) -> Self:
        if not self.enable_user_materials:
            self.pasted_text = ""
        if not self.enable_web_search:
            self.include_domains = ""
            return self
        if not self.include_domains.strip():
            return self
        valid_urls, invalid_urls = parse_and_validate_include_urls(self.include_domains)
        if invalid_urls:
            msg = "Invalid URLs (only http/https allowed):\n" + "\n".join(
                f"• {desc}" for desc in invalid_urls
            )
            raise ValueError(msg)
        self.include_domains = "\n".join(valid_urls)
        return self
