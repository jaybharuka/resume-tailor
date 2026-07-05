from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def _render():
    registry = PromptRegistry(prompts_root="prompts")
    return registry.render(
        "tailoring_rewrite", "v1",
        resume_json="{}", job_posting_json="{}", gap_analysis_json="{}",
    )


def test_tailoring_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="tailoring_rewrite", version="v1").one()
        assert row.template_path == "tailoring_rewrite/v1.jinja2"


def test_tailoring_prompt_instructs_against_fabricated_metrics():
    """Prompt-quality test (spec §4.3, §8): this is the ONLY defense against
    fabricated metrics, since no code-level guard exists for this vector."""
    rendered = _render()
    lowered = rendered.lower()
    assert "40%" in rendered  # the worked example's specific invented figure
    assert "fabricat" in lowered or "invent" in lowered
    assert "metric" in lowered or "number" in lowered or "percentage" in lowered


def test_tailoring_prompt_instructs_against_unearned_skills():
    rendered = _render()
    lowered = rendered.lower()
    assert "unearned" in lowered
    assert "matching_skills" in rendered


def test_tailoring_prompt_instructs_against_claiming_missing_skills():
    """Prompt-quality test (spec §4.1, §8): the code-level skills guard (§4.2)
    only checks whether a skill is unearned, not whether it specifically came
    from missing_skills, so this instruction is the only defense for this exact
    case (a skill that's also true content elsewhere wouldn't trip the guard)."""
    rendered = _render()
    lowered = rendered.lower()
    assert "missing_skills" in rendered
    assert "not" in lowered and "possess" in lowered


def test_tailoring_prompt_instructs_no_fabricated_entries_and_same_count():
    rendered = _render()
    lowered = rendered.lower()
    assert "same count" in lowered or "exactly the same" in lowered
    assert "may never add" in lowered


def test_tailoring_prompt_instructs_identity_anchored_change_paths():
    rendered = _render()
    assert 'projects["Inventory Tracker"].bullets[0]' in rendered
    assert "field_changed" in rendered
    assert "rationale" in rendered


def test_tailoring_prompt_embeds_all_three_input_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "tailoring_rewrite", "v1",
        resume_json='{"skills": ["Python"]}',
        job_posting_json='{"title": "Backend Engineer"}',
        gap_analysis_json='{"missing_skills": ["Docker"]}',
    )
    assert '{"skills": ["Python"]}' in rendered
    assert '{"title": "Backend Engineer"}' in rendered
    assert '{"missing_skills": ["Docker"]}' in rendered
