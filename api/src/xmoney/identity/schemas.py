"""HTTP shapes for registration and public handle lookup."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = Field(examples=["@amina"])
    phone: str = Field(examples=["+254712345678"])
    pin: str = Field(examples=["2580"], description="4-6 digits; stored only as an Argon2id hash")


class UserOut(BaseModel):
    id: UUID
    handle: str
    phone: str
    wallet_account_id: UUID
    created_at: datetime


class HandleOut(BaseModel):
    """Public. Enough to confirm a recipient exists, nothing that identifies a wallet."""

    handle: str
