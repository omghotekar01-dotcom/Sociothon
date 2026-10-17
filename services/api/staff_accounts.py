"""Administrator provisioned staff accounts; staff must not self-register into privileged roles."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.exc import IntegrityError

from .database import get_db
from .domain import audit
from .models import User, Zone
from .security import current_user, hash_password, public_user, require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["staff provisioning"])
AVAILABLE_DOMAINS = {"water", "electricity", "roads", "drainage", "waste", "streetlights", "general"}


class StaffCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["operator", "inspector"]
    domains: list[str] = Field(min_length=1, max_length=7)
    zones: list[str] = Field(min_length=1, max_length=100)
    electrical_qualified: bool = False
    reason: str = Field(min_length=5, max_length=2000)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        value = value.strip().lower()
        if value.count("@") != 1 or not value.split("@")[0] or "." not in value.split("@")[1] or any(c.isspace() for c in value):
            raise ValueError("Enter a valid staff email.")
        return value

    @field_validator("domains")
    @classmethod
    def valid_domains(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values) or set(values) - AVAILABLE_DOMAINS:
            raise ValueError("Choose distinct, supported departments.")
        return values

    @field_validator("zones")
    @classmethod
    def unique_zones(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("Choose distinct service zones.")
        return values


@router.post("/staff", status_code=201)
def provision_staff(body: StaffCreate, admin=Depends(current_user), db=Depends(get_db)):
    require_admin(admin)
    if set(body.zones) - {zone.id for zone in db.query(Zone).all()}:
        raise HTTPException(422, "One or more service zones do not exist.")
    if body.electrical_qualified and (body.role != "inspector" or "electricity" not in body.domains):
        raise HTTPException(422, "Electrical qualification requires an inspector with electricity permission.")
    if db.query(User).filter_by(email=body.email).first():
        raise HTTPException(409, "This staff email is already registered.")
    # Never return, audit, or store the raw password. The administrator is responsible
    # for sharing the initial password through a secure channel.
    new_staff = User(
        name=body.name.strip(), email=body.email, password_hash=hash_password(body.password),
        role=body.role, domains=body.domains, zones=body.zones, active=True,
        settings={"electrical_qualified": bool(body.electrical_qualified)},
    )
    db.add(new_staff)
    db.flush()
    audit(db, admin, None, "staff_provisioned", body.reason, after={
        "staff_id": new_staff.id, "role": new_staff.role,
        "domains": new_staff.domains, "zones": new_staff.zones,
        "electrical_qualified": body.electrical_qualified,
    })
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This staff email is already registered.") from None
    return public_user(new_staff) | {"active": new_staff.active}
