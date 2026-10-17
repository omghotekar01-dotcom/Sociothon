"""Acceptance checks for four-role civic case handoff."""
import uuid
from PIL import Image
from io import BytesIO


def test_staff_directory_and_new_inspector_assignment(login):
    admin,operator,citizen=login("admin"),login("operator"),login("citizen")
    email="ward-"+uuid.uuid4().hex[:10]+"@example.test"
    staff={"name":"Ward Inspector","email":email,"password":"DemoInitialPass-2026",
           "role":"inspector","domains":["water"],"zones":["river"],
           "reason":"Assign water inspections to the river ward"}
    assert citizen.post("/api/v1/admin/staff",json=staff).status_code==403
    created=admin.post("/api/v1/admin/staff",json=staff)
    assert created.status_code==201,created.text
    staff_id=created.json()["id"]
    assert "password" not in created.json()
    assert any(p["id"]==staff_id for p in operator.get("/api/v1/bootstrap").json()["inspectors"])
    assert admin.post("/api/v1/admin/staff",json=staff).status_code==409
    r=citizen.post("/api/v1/reports",json={
        "domain":"water","zone_id":"river","title":"Synthetic pipe observation",
        "description":"Observed damp ground near the market boundary.",
        "location":"Market entrance","idempotency_key":str(uuid.uuid4())})
    assert r.status_code==201,r.text
    case_id=r.json()["case_id"]
    detail=operator.get("/api/v1/cases/"+case_id)
    assert detail.status_code==200
    assert detail.json()["citizen_reports"][0]["description"].startswith("Observed damp")
    review=operator.post("/api/v1/cases/"+case_id+"/transition",
        json={"status":"investigating","reason":"Review original citizen description","version":detail.json()["version"]})
    assert review.status_code==200,review.text
    assigned=operator.post("/api/v1/cases/"+case_id+"/assign",
        json={"inspector_id":staff_id,"reason":"Assign newly provisioned field inspector","version":review.json()["version"]})
    assert assigned.status_code==200,assigned.text
    assert assigned.json()["assignment_team"]["lead"]["id"]==staff_id


def test_photograph_is_present_in_staff_evidence_passport(login):
    citizen,operator=login("citizen"),login("operator")
    r=citizen.post("/api/v1/reports",json={
        "domain":"roads","zone_id":"river","title":"Synthetic road damage",
        "description":"Road surface damage observed outside the market.",
        "location":"Market road","idempotency_key":str(uuid.uuid4())})
    assert r.status_code==201,r.text
    case_id=r.json()["case_id"]
    image=Image.new("RGB",(24,24),"blue")
    buff=BytesIO();image.save(buff,format="PNG")
    evidence=citizen.post("/api/v1/cases/"+case_id+"/evidence",
        files={"file":("evidence.png",buff.getvalue(),"image/png")},
        data={"notes":"Road surface photo","idempotency_key":str(uuid.uuid4())})
    assert evidence.status_code==200,evidence.text
    saved=operator.get("/api/v1/cases/"+case_id)
    assert saved.status_code==200
    images=[e for e in saved.json()["evidence_records"] if e["kind"]=="photograph"]
    assert len(images)==1
    assert operator.get(images[0]["url"]).status_code==200
