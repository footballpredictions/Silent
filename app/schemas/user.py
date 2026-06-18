import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr
from typing import Optional


class UserResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_id: str
    is_verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class SubscriptionInfo(BaseModel):
    is_active: bool
    plan_type: Optional[str] = None
    expires_at: Optional[datetime] = None
    days_left: int = 0


class DeviceInfo(BaseModel):
    id: uuid.UUID
    device_name: str
    device_type: str
    is_connected: bool
    last_connected: Optional[datetime] = None

    model_config = {"from_attributes": True}


class UserProfileResponse(BaseModel):
    id: uuid.UUID
    email: EmailStr
    display_id: str
    is_admin: bool = False
    subscription: SubscriptionInfo
    devices: list[DeviceInfo]
    devices_count: int
    connected_count: int = 0
    max_devices: int = 3
    vk_linked: bool = False
    vk_user_id: int | None = None

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class DeviceRenameRequest(BaseModel):
    device_name: str
