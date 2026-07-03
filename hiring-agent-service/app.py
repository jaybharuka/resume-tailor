import os
import sys
from pathlib import Path

HIRING_AGENT_REPO_PATH = os.environ.get(
    "HIRING_AGENT_REPO_PATH",
    str(Path(__file__).resolve().parent.parent.parent.parent.parent / "hiring-agent-imp"),
)
sys.path.insert(0, HIRING_AGENT_REPO_PATH)

from fastapi import FastAPI
from pydantic import BaseModel
from evaluator import ResumeEvaluator
from prompt import DEFAULT_MODEL, MODEL_PARAMETERS

RUBRIC_VERSION = "hiring-agent-v1"
HIRING_AGENT_SERVICE_VERSION = "0.1.0"

CATEGORY_MAXES = {
    "open_source": 35,
    "self_projects": 30,
    "production": 25,
    "technical_skills": 10,
}

app = FastAPI(title="Hiring Agent Service")


class EvaluateRequest(BaseModel):
    resume_text: str
    github_username: str | None = None


def compute_overall_score(evaluation) -> float:
    total = 0.0
    max_total = 0
    for category_name, category_data in evaluation.scores.model_dump().items():
        capped = min(category_data["score"], CATEGORY_MAXES.get(category_name, category_data["max"]))
        total += capped
        max_total += category_data["max"]
    total += evaluation.bonus_points.total
    total -= evaluation.deductions.total
    max_possible = max_total + 20
    return min(total, max_possible)


@app.post("/evaluate")
def evaluate(request: EvaluateRequest):
    model_params = MODEL_PARAMETERS.get(DEFAULT_MODEL)
    evaluator = ResumeEvaluator(model_name=DEFAULT_MODEL, model_params=model_params)
    evaluation = evaluator.evaluate_resume(request.resume_text)

    scores = evaluation.scores.model_dump()
    return {
        "overall_score": compute_overall_score(evaluation),
        "open_source_score": scores["open_source"]["score"],
        "projects_score": scores["self_projects"]["score"],
        "production_score": scores["production"]["score"],
        "technical_skills_score": scores["technical_skills"]["score"],
        "evidence": {name: data["evidence"] for name, data in scores.items()},
        "bonus_points": evaluation.bonus_points.model_dump(),
        "deductions": evaluation.deductions.model_dump(),
        "rubric_version": RUBRIC_VERSION,
        "hiring_agent_service_version": HIRING_AGENT_SERVICE_VERSION,
        "raw": evaluation.model_dump(),
    }


@app.get("/health")
def health():
    return {"status": "ok"}
