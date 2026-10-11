"""Public job bodies contain business inputs, never executors or local paths."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator


class QueryPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: StrictStr = Field(min_length=1, max_length=32000)
    collection: StrictStr = Field(default="default", pattern=r"^\w[\w.-]{0,127}$")
    top_k: StrictInt = Field(default=5, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    answer: StrictBool = True
    rewrite: StrictBool | None = None
    stream: StrictBool | None = None
    rerank: StrictBool = True
    request_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    require_citations: StrictBool = True


class AgentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_id: StrictStr = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    description: StrictStr = Field(min_length=1, max_length=32000)
    conversation_id: StrictStr | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    turn_id: StrictStr | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,128}$")
    clarification_for: StrictStr | None = Field(default=None, pattern=r"^route_[a-f0-9]{32}$")


class JobSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["query", "agent"]
    payload: dict[str, Any]
    timeout_seconds: float = Field(default=180, gt=0, le=3600, strict=True)
    max_attempts: StrictInt = Field(default=1, ge=1, le=3)

    @model_validator(mode="after")
    def business_payload(self):
        selected = QueryPayload if self.kind == "query" else AgentPayload
        self.payload = selected.model_validate(self.payload).model_dump(exclude_none=True)
        if not self.payload["query" if self.kind == "query" else "description"].strip():
            raise ValueError("Business text must not be blank")
        if self.kind == "agent" and self.max_attempts != 1:
            raise ValueError("Agent requests are not automatically retried after uncertain execution")
        # 为什么要有它：浮点NaN与无限JSON不能进入幂等指纹；大小约束覆盖嵌套filters，不只检查query长度。
        if len(json.dumps(self.payload, ensure_ascii=False, allow_nan=False).encode()) > 65536:
            raise ValueError("Job payload exceeds 64 KiB")
        return self
