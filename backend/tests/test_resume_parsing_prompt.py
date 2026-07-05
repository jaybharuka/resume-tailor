import re
from app.core.config import Settings
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience, Project, Education


def test_settings_default_prompts_root():
    settings = Settings(_env_file=None)
    assert settings.prompts_root == "./prompts"


def test_resume_parsing_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="resume_parsing", version="v1").one()
        assert row.template_path == "resume_parsing/v1.jinja2"


def test_resume_parsing_prompt_instructs_against_fabrication():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("resume_parsing", "v1", extracted_text="Jane Doe\nEngineer")
    lowered = rendered.lower()
    assert "do not" in lowered or "never" in lowered
    assert "fabricat" in lowered or "invent" in lowered
    assert "null" in lowered


def test_resume_parsing_prompt_json_shape_matches_resume_document_fields():
    """Ledger item: previously this prompt's fabrication-guard test only checked
    keyword presence, not that the prompt's declared JSON shape actually matches
    ResumeDocument's real fields (top-level and nested)."""
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("resume_parsing", "v1", extracted_text="Jane Doe\nEngineer")

    shape_start = rendered.index('{\n  "schema_version"')
    shape_end = rendered.index("\n\nIf the source text has no work experience")
    shape_block = rendered[shape_start:shape_end]

    keys_in_prompt = set(re.findall(r'"(\w+)":', shape_block))

    expected_keys = (
        set(ResumeDocument.model_fields.keys())
        | set(ContactInfo.model_fields.keys())
        | set(WorkExperience.model_fields.keys())
        | set(Project.model_fields.keys())
        | set(Education.model_fields.keys())
    )
    assert keys_in_prompt == expected_keys
