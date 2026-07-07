from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def _render():
    registry = PromptRegistry(prompts_root="prompts")
    return registry.render(
        "interview_questions", "v1",
        job_posting_json="{}", gap_analysis_json="{}",
    )


def test_interview_questions_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="interview_questions", version="v1").one()
        assert row.template_path == "interview_questions/v1.jinja2"


def test_interview_questions_prompt_instructs_minimum_count():
    rendered = _render()
    lowered = rendered.lower()
    assert "at least 5" in lowered


def test_interview_questions_prompt_instructs_against_generic_filler():
    rendered = _render()
    lowered = rendered.lower()
    assert "generic filler" in lowered or "tell me about yourself" in lowered


def test_interview_questions_prompt_references_missing_skills_and_experience_gap():
    rendered = _render()
    lowered = rendered.lower()
    assert "missing_skills" in rendered
    assert "experience_gap_notes" in rendered


def test_interview_questions_prompt_embeds_both_input_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "interview_questions", "v1",
        job_posting_json='{"title": "Backend Engineer"}',
        gap_analysis_json='{"missing_skills": ["Docker"]}',
    )
    assert '{"title": "Backend Engineer"}' in rendered
    assert '{"missing_skills": ["Docker"]}' in rendered
