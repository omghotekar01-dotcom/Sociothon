import json
import pytest
from services.api import ai_investigator as ai

GOOD = {
 "overview":"Coded metadata indicates an open record; field confirmation is still missing.",
 "hypotheses":[{"label":"Possible measurement issue","explanation":"Unverified interpretation; check source quality.","source_ids":["case_metadata"]}],
 "missing_evidence":[{"label":"Field evidence","explanation":"No verified field check was provided.","source_ids":[]}],
 "next_checks":[{"label":"Ask authorized staff to review","explanation":"Check meter provenance without operating equipment.","source_ids":["case_metadata"]}],
}

def test_gemini_parser_and_reference_validation():
    assert ai.validate_result(GOOD, {"case_metadata":"Stored coded metadata"})["hypotheses"][0]["source_ids"] == ["case_metadata"]
    invalid = json.loads(json.dumps(GOOD))
    invalid["hypotheses"][0]["source_ids"] = ["invented_citation"]
    with pytest.raises(ValueError):
        ai.validate_result(invalid, {"case_metadata":"Stored coded metadata"})

def test_payload_never_contains_citizen_text_or_field_notes():
    class CaseStub:
        domain="water"
        zone_id="river"
        severity="high"
        status="investigating"
        provenance="synthetic"
        asset_id="meter-1"
        assigned_to=None
        version=2
        evidence={"untrusted_private_note":"Do not send this field to Gemini"}
        title="Private complaint title"
        summary="Private address and reporter message"
        priority_review={"score":58}
    snapshot,sources=ai.compact_context(CaseStub(), [])
    serialized=json.dumps(snapshot)
    assert "Private complaint" not in serialized and "Private address" not in serialized
    assert "untrusted_private_note" not in serialized
    assert set(sources) == {"case_metadata"}

def test_staff_only_endpoint_missing_key_and_mock_gemini(login, monkeypatch):
    citizen=login("citizen")
    assert citizen.get("/api/v1/ai/status").status_code == 403
    operator=login("operator")
    status=operator.get("/api/v1/ai/status")
    assert status.status_code == 200
    cases=operator.get("/api/v1/cases").json()
    assert cases, "Synthetic demo should seed authorized cases"
    case_id=cases[0]["id"]
    monkeypatch.setattr(ai,"local_config",lambda name: "" if name=="GEMINI_API_KEY" else "gemini-2.5-flash")
    assert operator.post("/api/v1/ai/investigate",json={"case_id":case_id,"focus":"evidence"}).status_code == 503
    monkeypatch.setattr(ai,"local_config",lambda name: "test-key" if name=="GEMINI_API_KEY" else "gemini-2.5-flash")
    calls=[]
    def fake_generate(data,key,model):
        calls.append(data)
        return GOOD
    monkeypatch.setattr(ai,"gemini_generate",fake_generate)
    response=operator.post("/api/v1/ai/investigate",json={"case_id":case_id,"focus":"water"})
    assert response.status_code == 200,response.text
    assert response.json()["result"]["next_checks"]
    assert calls[0]["focus"]=="water"
    assert "title" not in calls[0]["snapshot"]["case"]
    assert citizen.post("/api/v1/ai/investigate",json={"case_id":case_id}).status_code == 403

def test_gemini_bad_citation_is_not_exposed_as_verified(login,monkeypatch):
    operator=login("operator")
    case_id=operator.get("/api/v1/cases").json()[0]["id"]
    monkeypatch.setattr(ai,"local_config",lambda name:"test-key" if name=="GEMINI_API_KEY" else "gemini-2.5-flash")
    bogus=json.loads(json.dumps(GOOD))
    bogus["missing_evidence"][0]["source_ids"]=["imaginary"]
    monkeypatch.setattr(ai,"gemini_generate",lambda *args:bogus)
    response=operator.post("/api/v1/ai/investigate",json={"case_id":case_id})
    assert response.status_code == 502
    assert "failed evidence validation" in response.json()["detail"]
