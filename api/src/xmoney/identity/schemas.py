"""HTTP shapes for registration and public handle lookup."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    handle: str = Field(examples=["@amina"])
    phone: str = Field(examples=["+254712345678"])


class UserOut(BaseModel):
    id: UUID
    handle: str
    phone: str
    wallet_account_id: UUID
    created_at: datetime


class HandleOut(BaseModel):
    handle: str
    user_id: UUID
    wallet_account_id: UUID
