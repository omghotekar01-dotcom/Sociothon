"""Audited asset/zone registry administration. Registry edits are not model fits."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal
from .database import get_db
from .security import current_user, require_admin
from .models import Asset, Zone
from .domain import audit

router = APIRouter(prefix="/api/v1/admin")

class ZoneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]{2,60}$")
    name: str = Field(min_length=3, max_length=100)
    population: int | None = Field(default=None, ge=1, le=100000000)
    reason: str = Field(min_length=5, max_length=2000)

class AssetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9-]{2,100}$")
    name: str = Field(min_length=3, max_length=160)
    domain: Literal["water", "electricity", "roads", "drainage", "waste", "streetlights", "general"]
    zone_id: str
    kind: str = Field(min_length=3, max_length=100)
    x: float = Field(ge=0, le=100, allow_inf_nan=False)
    y: float = Field(ge=0, le=100, allow_inf_nan=False)
    provenance: Literal["Synthetic", "Uploaded", "Measured"] = "Uploaded"
    reason: str = Field(min_length=5, max_length=2000)

@router.post("/zones", status_code=201)
def create_zone(body: ZoneInput, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    if db.get(Zone, body.id):
        raise HTTPException(409, "Zone ID already exists.")
    value = body.model_dump(exclude={"reason"})
    db.add(Zone(**value, geometry={"source":"Schematic registry"}))
    audit(db, user, None, "zone_created", body.reason, after=value)
    db.commit()
    return value

@router.post("/assets", status_code=201)
def create_asset(body: AssetInput, user=Depends(current_user), db=Depends(get_db)):
    require_admin(user)
    if db.get(Asset, body.id):
        raise HTTPException(409, "Asset ID already exists.")
    if not db.get(Zone, body.zone_id):
        raise HTTPException(422, "Choose an existing registered zone.")
    value = body.model_dump(exclude={"reason"})
    db.add(Asset(**value, properties={"registry_note":"No readings or model conclusions are inferred from registration."}))
    audit(db, user, None, "asset_created", body.reason, after=value)
    db.commit()
    return value
