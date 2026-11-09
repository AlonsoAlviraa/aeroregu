"""Typed outputs for the specialist agents.

Values are quotations and spans. These models have no field for a number
the model computed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SpanQuote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value_text: str
    unit_text: str = ""
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)


class ExtractorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: Literal[False] = False
    confidence: Literal["low", "high"] = "high"
    fields: list[SpanQuote]
    clause_ids: list[str]
    assumptions: list[SpanQuote]


class ChallengerOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: Literal[False] = False
    confidence: Literal["low", "high"] = "high"
    attack: Literal["hit", "miss"]
    reason: str
    evidence_span: str


class MapperLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirement_id: str
    evidence_id: str
    span_start: int = Field(ge=0)
    span_end: int = Field(ge=0)


class MapperOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: Literal[False] = False
    links: list[MapperLink]


class ScribeSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    ledger_event_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ScribeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: Literal[False] = False
    sentences: list[ScribeSentence]


class JudgeInput(BaseModel):
    """Gold and verdict only. Reasoning is rejected."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    verdict: str
    gold_label: str


class AbstainOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstain: Literal[True] = True
    reason: str
    escalate_to: Literal["human_engineer"] = "human_engineer"
