from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def _render():
    registry = PromptRegistry(prompts_root="prompts")
    return registry.render(
        "cover_letter", "v1",
        resume_json="{}", job_posting_json="{}", gap_analysis_json="{}",
    )


def test_cover_letter_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="cover_letter", version="v1").one()
        assert row.template_path == "cover_letter/v1.jinja2"


def test_cover_letter_prompt_instructs_against_unearned_skills():
    rendered = _render()
    lowered = rendered.lower()
    assert "unearned" in lowered or "flask" in lowered
    assert "matching_skills" in rendered


def test_cover_letter_prompt_instructs_against_claiming_missing_skills():
    rendered = _render()
    lowered = rendered.lower()
    assert "missing_skills" in rendered
    assert "not" in lowered


def test_cover_letter_prompt_instructs_against_fabricated_metrics():
    rendered = _render()
    lowered = rendered.lower()
    assert "fabricat" in lowered or "invent" in lowered
    assert "metric" in lowered or "achievement" in lowered


def test_cover_letter_prompt_embeds_all_three_input_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "cover_letter", "v1",
        resume_json='{"skills": ["Python"]}',
        job_posting_json='{"title": "Backend Engineer"}',
        gap_analysis_json='{"missing_skills": ["Docker"]}',
    )
    assert '{"skills": ["Python"]}' in rendered
    assert '{"title": "Backend Engineer"}' in rendered
    assert '{"missing_skills": ["Docker"]}' in rendered
