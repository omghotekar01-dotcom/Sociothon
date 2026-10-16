"""Explicit interval imports. UTC interval-start convention, atomic preview/commit."""
import csv
import hashlib
import io
import math
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from .models import Asset, Reading, Upload
from .security import in_scope

FIELDS = ["id", "asset_id", "zone_id", "timestamp", "interval_minutes", "quantity", "unit", "source", "quality_flag"]
OPTIONAL_FIELDS = ["voltage", "voltage_unit", "power_kw", "power_unit", "current_a", "current_unit"]
OPTIONAL_MEASUREMENTS = {
    "voltage": ("voltage_unit", "V", {"v", "volt", "volts"}, 1000.),
    "power_kw": ("power_unit", "kW", {"kw", "kilowatt", "kilowatts"}, 100000.),
    "current_a": ("current_unit", "A", {"a", "amp", "amps", "ampere", "amperes"}, 1000000.),
}


def _same_optional_measurements(left, right):
    left, right = left or {}, right or {}
    for field in OPTIONAL_MEASUREMENTS:
        left_value = left.get(field)
        right_value = right.get(field)
        left_value = None if left_value in (None, "") else float(left_value)
        right_value = None if right_value in (None, "") else float(right_value)
        if left_value != right_value:
            return False
    return True


def preview_csv(db, user, content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "CSV must use UTF-8 encoding.") from exc
    reader = csv.DictReader(io.StringIO(text))
    missing = set(FIELDS) - set(reader.fieldnames or [])
    if missing:
        raise HTTPException(422, "Missing columns: " + ", ".join(sorted(missing)))
    if any("cumulative" in str(name).lower() for name in reader.fieldnames):
        raise HTTPException(422, "Cumulative counters are unsupported. Supply declared interval quantities.")
    rows, errors, duplicates, occupied, last_time = [], [], 0, {}, {}
    for line, raw in enumerate(reader, start=2):
        if line > 20001:
            raise HTTPException(413, "Maximum 20,000 readings per import.")
        try:
            if None in raw or any(raw.get(field) is None for field in FIELDS):
                raise ValueError("Row has missing or extra cells; match the CSV template columns.")
            asset = db.get(Asset, raw["asset_id"])
            if not asset or asset.domain not in {"water", "electricity"}:
                raise ValueError("Unknown water/electricity asset.")
            if not in_scope(user, asset.domain, asset.zone_id):
                raise ValueError("Asset outside your authorized scope.")
            if raw["zone_id"] != asset.zone_id:
                raise ValueError("Zone does not match asset.")
            if not raw["id"].strip() or len(raw["id"]) > 100:
                raise ValueError("A reading ID of at most 100 characters is required.")
            stamp = datetime.fromisoformat(raw["timestamp"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Timezone required: use Z or an explicit UTC offset.")
            stamp = stamp.astimezone(timezone.utc)
            minutes = float(raw["interval_minutes"])
            if not math.isfinite(minutes) or minutes <= 0 or minutes > 1440:
                raise ValueError("interval_minutes must be between 0 and 1440.")
            end = stamp + timedelta(minutes=minutes)
            quality = raw["quality_flag"].strip().lower()
            if quality not in {"valid", "missing", "invalid"}:
                raise ValueError("quality_flag must be valid, missing or invalid.")
            quantity = None if raw["quantity"].strip() == "" else float(raw["quantity"])
            if quantity is None and quality == "valid":
                raise ValueError("Missing quantity cannot be valid; declare missing, never fill with zero.")
            if quantity is not None and (not math.isfinite(quantity) or quantity < 0):
                raise ValueError("Quantity must be a finite nonnegative interval measurement.")
            unit = raw["unit"].strip()
            allowed = {"L": 1.0, "litres": 1.0, "m3": 1000.0} if asset.domain == "water" else {"kWh": 1.0, "Wh": 0.001}
            if unit not in allowed:
                raise ValueError("Unsupported interval unit; use " + ", ".join(allowed))
            for field, (unit_field, canonical_unit, aliases, maximum) in OPTIONAL_MEASUREMENTS.items():
                value_text = (raw.get(field) or "").strip()
                measured_unit = (raw.get(unit_field) or "").strip()
                if value_text:
                    if asset.domain != "electricity":
                        raise ValueError(f"{field} telemetry is only supported for electricity assets.")
                    value = float(value_text)
                    if not math.isfinite(value) or not 0 <= value <= maximum:
                        raise ValueError(f"{field} must be a finite measured value from 0 to {maximum:g} {canonical_unit}.")
                    if measured_unit.casefold() not in aliases:
                        raise ValueError(f"Measured {field} requires an explicit {unit_field} of {canonical_unit}.")
                elif measured_unit:
                    raise ValueError(f"{unit_field} requires a measured {field} value.")
            canonical = "L" if asset.domain == "water" else "kWh"
            iso = stamp.isoformat()
            normalized_quantity = quantity * allowed[unit] if quantity is not None else None
            candidates = [r for r in rows if r["id"] == raw["id"] or (r["asset_id"] == asset.id and r["timestamp"] == iso)]
            previous = db.get(Reading, raw["id"])
            if previous is None:
                previous = next((r for r in db.query(Reading).filter_by(asset_id=asset.id).all() if datetime.fromisoformat(r.timestamp.replace("Z", "+00:00")) == stamp), None)
            if previous:
                candidates.append({**{k: getattr(previous, k) for k in ("asset_id", "timestamp", "interval_minutes", "quantity", "unit", "quality_flag")}, "original": previous.original or {}})
            if candidates:
                if any(
                    r["asset_id"] != asset.id
                    or datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) != stamp
                    or r["interval_minutes"] != minutes
                    or r["quantity"] != normalized_quantity
                    or r["unit"] != canonical
                    or r["quality_flag"] != quality
                    or not _same_optional_measurements(r.get("original"), raw)
                    for r in candidates
                ):
                    raise ValueError("Reading ID or timestamp conflicts with different existing values.")
                duplicates += 1
                continue
            if asset.id in last_time and stamp < last_time[asset.id]:
                raise ValueError("Rows must be ordered by timestamp within each asset.")
            if asset.id not in occupied:
                occupied[asset.id] = [(datetime.fromisoformat(r.timestamp.replace("Z", "+00:00")), datetime.fromisoformat(r.timestamp.replace("Z", "+00:00")) + timedelta(minutes=r.interval_minutes)) for r in db.query(Reading).filter_by(asset_id=asset.id).all()]
            if any(stamp < old_end and end > old_start for old_start, old_end in occupied[asset.id]):
                raise ValueError("Interval overlaps an existing or previewed interval.")
            occupied[asset.id].append((stamp, end))
            last_time[asset.id] = stamp
            rows.append({"id": raw["id"], "asset_id": asset.id, "zone_id": asset.zone_id, "domain": asset.domain, "timestamp": iso, "interval_minutes": minutes, "quantity": normalized_quantity, "unit": canonical, "source": "Uploaded", "quality_flag": quality, "original": raw})
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"row": line, "error": str(exc)})
    upload = Upload(user_id=user.id, checksum=hashlib.sha256(content).hexdigest(), rows=rows, errors=errors)
    db.add(upload)
    db.commit()
    return {"id": upload.id, "accepted": len(rows), "rejected": len(errors), "duplicates": duplicates, "errors": errors, "rows": rows[:20], "status": upload.status, "policy": "Commit requires a fully valid preview. Late data is stored; explicit analysis rerun is required."}
