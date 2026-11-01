from pydantic import BaseModel
from agent.ledger import resolve_value_ref, available_refs, MissingProvenance
from agent.llm import generate_json

profile = {
    "dob": {"key": "dob", "value": "2004-05-12",
            "provenance": {"kind": "document", "document_id": "doc1", "confidence": 0.95}},
    "family_income": {"key": "family_income", "value": "180000",
                      "provenance": {"kind": "document", "document_id": "doc2", "confidence": 0.6}},
}

print("Refs shown to LLM:", available_refs(profile))
print("profile.dob ->", resolve_value_ref(profile, "profile.dob"))
for ref in ["profile.family_income", "profile.aadhaar"]:
    try:
        resolve_value_ref(profile, ref)
    except MissingProvenance as e:
        print(f"{ref} blocked:", e)

class Capital(BaseModel):
    country: str
    capital: str

print("Gemini JSON:", generate_json("Capital of India? Answer as JSON.", Capital))
