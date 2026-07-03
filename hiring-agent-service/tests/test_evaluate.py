import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
import app as app_module
from models import EvaluationData


class FakeEvaluator:
    def __init__(self, model_name, model_params):
        pass

    def evaluate_resume(self, resume_text: str) -> EvaluationData:
        return EvaluationData.model_validate({
            "scores": {
                "open_source": {"score": 30, "max": 35, "evidence": "3 popular repos"},
                "self_projects": {"score": 25, "max": 30, "evidence": "2 solid projects"},
                "production": {"score": 20, "max": 25, "evidence": "2 years production"},
                "technical_skills": {"score": 8, "max": 10, "evidence": "Python, FastAPI"},
            },
            "bonus_points": {"total": 5, "breakdown": "Active OSS contributor"},
            "deductions": {"total": 0, "reasons": "No deductions"},
            "key_strengths": ["Strong OSS presence"],
            "areas_for_improvement": ["More production depth"],
        })


def test_evaluate_returns_structured_score(monkeypatch):
    monkeypatch.setattr(app_module, "ResumeEvaluator", FakeEvaluator)
    client = TestClient(app_module.app)

    response = client.post("/evaluate", json={
        "resume_text": "Jane Doe, Senior Backend Engineer...",
        "github_username": None,
    })

    assert response.status_code == 200
    body = response.json()
    assert body["overall_score"] == 88.0
    assert body["open_source_score"] == 30
    assert body["rubric_version"] == "hiring-agent-v1"
    assert body["raw"]["bonus_points"]["total"] == 5


def test_health_endpoint():
    client = TestClient(app_module.app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
