"""Public platform contracts shared by health and discovery endpoints."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class LivenessResponse(BaseModel):
    status: Literal["ok"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool]


class ApiRootResponse(BaseModel):
    name: str
    version: str
    contract: Literal[1]
