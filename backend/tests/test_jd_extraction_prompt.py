import re
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion
from app.models.job_posting import JobPostingDocument


def test_jd_extraction_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="jd_extraction", version="v1").one()
        assert row.template_path == "jd_extraction/v1.jinja2"


def test_jd_extraction_prompt_instructs_against_fabrication():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    lowered = rendered.lower()
    assert "do not" in lowered or "never" in lowered
    assert "fabricat" in lowered or "invent" in lowered
    assert "null" in lowered


def test_jd_extraction_prompt_embeds_concrete_tie_breaking_examples():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    lowered = rendered.lower()
    assert "example 1" in lowered
    assert "example 2" in lowered
    assert "qualifications" in lowered and "requirements" in lowered


def test_jd_extraction_prompt_addresses_title_fabrication_risk():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    lowered = rendered.lower()
    assert "untitled" in lowered
    assert "required" in lowered


def test_jd_extraction_prompt_json_shape_matches_job_posting_document_fields():
    """Ledger item: previously the JSON-shape correctness of this prompt's output
    block was only verified manually during code review, not by an automated
    test. This ties the prompt's declared field list directly to
    JobPostingDocument's actual fields, so schema drift between the two would
    fail this test."""
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("jd_extraction", "v1", raw_text="Barista at Corner Cafe.")
    shape_block = re.search(r"\{[^{}]*\}", rendered, re.DOTALL).group(0)
    keys_in_prompt = re.findall(r'"(\w+)":', shape_block)
    assert keys_in_prompt == list(JobPostingDocument.model_fields.keys())
