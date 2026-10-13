"""HTTP shapes for sign-in."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SignInIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    phone: str = Field(examples=["+254712345678"])
    pin: str = Field(examples=["2580"])


class ChallengeOut(BaseModel):
    challenge_id: UUID
    expires_at: datetime
    delivery: str = "sandbox_inbox"


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    challenge_id: UUID
    code: str = Field(examples=["482913"])


class MeOut(BaseModel):
    user_id: UUID
    handle: str
    phone: str
    wallet_account_id: UUID
