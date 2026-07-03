from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion
from app.core.llm.prompt_registry import PromptRegistry


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def test_sync_to_db_creates_one_row_per_template(tmp_path):
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tailoring_rewrite").mkdir(parents=True)
    (prompts_dir / "tailoring_rewrite" / "v1.jinja2").write_text("Rewrite: {{ bullet }}")

    registry = PromptRegistry(prompts_root=str(prompts_dir))
    db = _make_db()

    count = registry.sync_to_db(db)

    assert count == 1
    row = db.query(PromptVersion).one()
    assert row.task_type == "tailoring_rewrite"
    assert row.version == "v1"


def test_sync_to_db_is_idempotent(tmp_path):
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tailoring_rewrite").mkdir(parents=True)
    (prompts_dir / "tailoring_rewrite" / "v1.jinja2").write_text("Rewrite: {{ bullet }}")

    registry = PromptRegistry(prompts_root=str(prompts_dir))
    db = _make_db()

    registry.sync_to_db(db)
    second_run_count = registry.sync_to_db(db)

    assert second_run_count == 0
    assert db.query(PromptVersion).count() == 1


def test_render_fills_template_variables(tmp_path):
    prompts_dir = tmp_path / "prompts"
    (prompts_dir / "tailoring_rewrite").mkdir(parents=True)
    (prompts_dir / "tailoring_rewrite" / "v1.jinja2").write_text("Rewrite: {{ bullet }}")
    registry = PromptRegistry(prompts_root=str(prompts_dir))

    rendered = registry.render("tailoring_rewrite", "v1", bullet="Built a thing")

    assert rendered == "Rewrite: Built a thing"
