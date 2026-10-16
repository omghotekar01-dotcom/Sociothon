import csv
import io
from types import SimpleNamespace

import pytest

from services.api.ingestion import FIELDS, OPTIONAL_FIELDS, preview_csv


class Query:
    def filter_by(self, **_filters):
        return self

    def all(self):
        return []


class Database:
    def __init__(self, domain="electricity"):
        self.asset = SimpleNamespace(id="meter-1", domain=domain, zone_id="river")
        self.added = []

    def get(self, model, ident):
        if getattr(model, "__name__", "") == "Asset" and ident == self.asset.id:
            return self.asset
        return None

    def query(self, _model):
        return Query()

    def add(self, row):
        self.added.append(row)

    def commit(self):
        pass


def csv_bytes(voltage="230", voltage_unit="V", domain="electricity", power_kw="", power_unit="", current_a="", current_unit=""):
    stream = io.StringIO()
    fields = FIELDS + OPTIONAL_FIELDS
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow({
        "id": "reading-1", "asset_id": "meter-1", "zone_id": "river",
        "timestamp": "2026-10-01T00:00:00Z", "interval_minutes": "60",
        "quantity": "0", "unit": "L" if domain == "water" else "kWh", "source": "uploaded",
        "quality_flag": "valid", "voltage": voltage, "voltage_unit": voltage_unit,
        "power_kw": power_kw, "power_unit": power_unit, "current_a": current_a, "current_unit": current_unit,
    })
    return stream.getvalue().encode()


def user():
    return SimpleNamespace(id="operator-1", role="operator", domains=["electricity", "water"], zones=["river"])


def test_electricity_csv_accepts_and_preserves_explicit_measured_voltage():
    result = preview_csv(Database(), user(), csv_bytes("229.5", "volts"))

    assert result["accepted"] == 1
    assert result["rows"][0]["quantity"] == 0
    assert result["rows"][0]["original"]["voltage"] == "229.5"
    assert result["rows"][0]["original"]["voltage_unit"] == "volts"


def test_electricity_csv_accepts_explicit_power_and_current_units():
    result = preview_csv(Database(), user(), csv_bytes(power_kw="2.4", power_unit="kilowatts", current_a="8", current_unit="amps"))

    assert result["accepted"] == 1
    assert result["rows"][0]["original"]["power_kw"] == "2.4"
    assert result["rows"][0]["original"]["power_unit"] == "kilowatts"
    assert result["rows"][0]["original"]["current_a"] == "8"
    assert result["rows"][0]["original"]["current_unit"] == "amps"


def test_duplicate_timestamp_with_changed_power_or_current_is_a_conflict():
    first = next(csv.DictReader(io.StringIO(csv_bytes(power_kw="2", power_unit="kW", current_a="8", current_unit="A").decode())))
    second = {**first, "current_a": "9"}
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS + OPTIONAL_FIELDS)
    writer.writeheader()
    writer.writerows((first, second))

    result = preview_csv(Database(), user(), stream.getvalue().encode())

    assert result["accepted"] == 1
    assert result["rejected"] == 1
    assert "conflicts with different existing values" in result["errors"][0]["error"]


@pytest.mark.parametrize(
    ("voltage", "voltage_unit", "message"),
    [
        ("230", "", "explicit voltage_unit"),
        ("230", "kV", "explicit voltage_unit"),
        ("1001", "V", "0 to 1000 V"),
        ("NaN", "V", "finite measured value"),
        ("", "V", "requires a measured voltage value"),
    ],
)
def test_voltage_csv_rejects_ambiguous_or_invalid_measurements(voltage, voltage_unit, message):
    result = preview_csv(Database(), user(), csv_bytes(voltage, voltage_unit))

    assert result["accepted"] == 0
    assert result["rejected"] == 1
    assert message in result["errors"][0]["error"]


def test_water_csv_cannot_attach_electric_voltage_fields():
    result = preview_csv(Database(domain="water"), user(), csv_bytes("230", "V", domain="water"))

    assert result["accepted"] == 0
    assert "only supported for electricity" in result["errors"][0]["error"]


@pytest.mark.parametrize(
    ("power", "power_unit", "current", "current_unit", "message"),
    [
        ("2", "", "", "", "explicit power_unit"),
        ("", "kW", "", "", "requires a measured power_kw value"),
        ("-1", "kW", "", "", "finite measured value"),
        ("", "", "5", "", "explicit current_unit"),
        ("", "", "NaN", "A", "finite measured value"),
        ("", "", "", "A", "requires a measured current_a value"),
    ],
)
def test_power_and_current_import_require_valid_explicit_units(power, power_unit, current, current_unit, message):
    result = preview_csv(Database(), user(), csv_bytes(power_kw=power, power_unit=power_unit, current_a=current, current_unit=current_unit))

    assert result["accepted"] == 0
    assert result["rejected"] == 1
    assert message in result["errors"][0]["error"]


@pytest.mark.parametrize(("second_voltage", "duplicates", "rejected"), [("230.0", 1, 0), ("220", 0, 1)])
def test_same_timestamp_duplicate_must_match_voltage(second_voltage, duplicates, rejected):
    first = next(csv.DictReader(io.StringIO(csv_bytes().decode())))
    second = {**first, "voltage": second_voltage}
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=FIELDS + OPTIONAL_FIELDS)
    writer.writeheader()
    writer.writerows((first, second))

    result = preview_csv(Database(), user(), stream.getvalue().encode())

    assert result["accepted"] == 1
    assert result["duplicates"] == duplicates
    assert result["rejected"] == rejected
