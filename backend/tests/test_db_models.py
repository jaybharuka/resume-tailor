import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import make_engine, make_session_factory
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession,
    PipelineRun, EvaluationRun, GeneratedDocument, PromptVersion, LLMCall, GapAnalysis,
)


def test_all_tables_create_and_accept_a_linked_row():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
        db.add(resume)
        db.flush()

        version = ResumeVersion(
            resume_id=resume.id, version_number=1,
            resume_json={"schema_version": 1, "contact": {"full_name": "Jane"}},
            produced_by_stage="upload",
        )
        job = JobPosting(source_url="https://example.com/job", source_provider="greenhouse")
        db.add_all([version, job])
        db.flush()

        session = TailoringSession(resume_id=resume.id, job_posting_id=job.id, status="created")
        db.add(session)
        db.flush()

        pipeline_run = PipelineRun(session_id=session.id, stage_name="resume_parsing", status="succeeded")
        evaluation = EvaluationRun(
            session_id=session.id, resume_version_id=version.id,
            overall_score=85.0, raw_response_json={"overall_score": 85.0},
        )
        document = GeneratedDocument(
            session_id=session.id, document_type="ats_report",
            content="report body", version_number=1,
        )
        prompt_version = PromptVersion(
            task_type="tailoring_rewrite", name="tailoring_rewrite", version="v1",
            template_path="prompts/tailoring_rewrite/v1.jinja2",
        )
        gap_analysis = GapAnalysis(
            session_id=session.id, resume_version_id=version.id, job_posting_id=job.id,
            analysis_json={"schema_version": 1, "matching_skills": ["Python"]},
        )
        db.add_all([pipeline_run, evaluation, document, prompt_version, gap_analysis])
        db.flush()

        llm_call = LLMCall(
            session_id=session.id, prompt_version_id=prompt_version.id,
            provider="gemini", model="gemini-1.5-flash", task_type="tailoring_rewrite",
            temperature=0.7, request_payload={"prompt": "hi"}, response_payload={"text": "hello"},
            validated=True, latency_ms=250,
        )
        db.add(llm_call)
        db.commit()

        assert db.query(Resume).count() == 1
        assert db.query(LLMCall).count() == 1
        assert db.query(EvaluationRun).first().overall_score == 85.0
        assert db.query(GapAnalysis).first().analysis_json["matching_skills"] == ["Python"]


def test_deleting_a_session_cascades_to_its_dependent_rows():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
        db.add(resume)
        db.flush()

        version = ResumeVersion(
            resume_id=resume.id, version_number=1,
            resume_json={"schema_version": 1, "contact": {"full_name": "Jane"}},
            produced_by_stage="upload",
        )
        job = JobPosting(source_url="https://example.com/job", source_provider="greenhouse")
        db.add_all([version, job])
        db.flush()

        session = TailoringSession(resume_id=resume.id, job_posting_id=job.id, status="created")
        db.add(session)
        db.flush()

        pipeline_run = PipelineRun(session_id=session.id, stage_name="resume_parsing", status="succeeded")
        evaluation = EvaluationRun(
            session_id=session.id, resume_version_id=version.id,
            overall_score=85.0, raw_response_json={"overall_score": 85.0},
        )
        document = GeneratedDocument(
            session_id=session.id, document_type="ats_report",
            content="report body", version_number=1,
        )
        prompt_version = PromptVersion(
            task_type="tailoring_rewrite", name="tailoring_rewrite", version="v1",
            template_path="prompts/tailoring_rewrite/v1.jinja2",
        )
        gap_analysis = GapAnalysis(
            session_id=session.id, resume_version_id=version.id, job_posting_id=job.id,
            analysis_json={"schema_version": 1, "matching_skills": ["Python"]},
        )
        db.add_all([pipeline_run, evaluation, document, prompt_version, gap_analysis])
        db.flush()

        llm_call = LLMCall(
            session_id=session.id, prompt_version_id=prompt_version.id,
            provider="gemini", model="gemini-1.5-flash", task_type="tailoring_rewrite",
            temperature=0.7, request_payload={"prompt": "hi"}, response_payload={"text": "hello"},
            validated=True, latency_ms=250,
        )
        db.add(llm_call)
        db.commit()

        session_id = session.id
        resume_id = resume.id
        job_id = job.id
        version_id = version.id
        prompt_version_id = prompt_version.id

        db.delete(session)
        db.commit()

    with SessionFactory() as db:
        assert db.query(PipelineRun).filter_by(session_id=session_id).count() == 0
        assert db.query(EvaluationRun).filter_by(session_id=session_id).count() == 0
        assert db.query(GeneratedDocument).filter_by(session_id=session_id).count() == 0
        assert db.query(LLMCall).filter_by(session_id=session_id).count() == 0
        assert db.query(GapAnalysis).filter_by(session_id=session_id).count() == 0

        assert db.query(Resume).filter_by(id=resume_id).count() == 1
        assert db.query(JobPosting).filter_by(id=job_id).count() == 1
        assert db.query(ResumeVersion).filter_by(id=version_id).count() == 1
        assert db.query(PromptVersion).filter_by(id=prompt_version_id).count() == 1


def test_prompt_version_unique_constraint_rejects_duplicates():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        db.add(PromptVersion(
            task_type="resume_parsing", name="resume_parsing", version="v1", template_path="a.jinja2",
        ))
        db.commit()

        db.add(PromptVersion(
            task_type="resume_parsing", name="resume_parsing", version="v1", template_path="b.jinja2",
        ))
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_referenced_prompt_version_is_restricted():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        prompt_version = PromptVersion(
            task_type="resume_parsing", name="resume_parsing", version="v1", template_path="a.jinja2",
        )
        db.add(prompt_version)
        db.commit()

        llm_call = LLMCall(
            session_id=None, prompt_version_id=prompt_version.id, provider="nvidia",
            model="m1", task_type="resume_parsing", validated=True,
        )
        db.add(llm_call)
        db.commit()

        db.delete(prompt_version)
        with pytest.raises(IntegrityError):
            db.commit()
