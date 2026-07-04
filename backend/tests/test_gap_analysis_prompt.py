from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def test_gap_analysis_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="gap_analysis", version="v1").one()
        assert row.template_path == "gap_analysis/v1.jinja2"


def test_gap_analysis_prompt_instructs_strict_matching_with_adjacent_example():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "django" in lowered and "flask" in lowered
    assert "not a match" in lowered or "not_a_match" in lowered or "not match" in lowered


def test_gap_analysis_prompt_embeds_synonym_worked_example():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "javascript" in lowered
    assert "abbreviation" in lowered or "synonym" in lowered


def test_gap_analysis_prompt_instructs_missing_skills_subset_rule():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "generally expected" in lowered
    assert "literally" in lowered


def test_gap_analysis_prompt_embeds_both_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "gap_analysis", "v1",
        resume_json='{"skills": ["Python"]}',
        job_posting_json='{"title": "Backend Engineer"}',
    )
    assert '{"skills": ["Python"]}' in rendered
    assert '{"title": "Backend Engineer"}' in rendered
