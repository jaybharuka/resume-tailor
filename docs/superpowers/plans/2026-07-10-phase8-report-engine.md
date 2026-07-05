# Phase 8: Report Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five report/document types to the pipeline: two read-only computed views (ATS report, skill-gap report) over existing `EvaluationRun`/`GapAnalysis` data, and three new LLM-backed stages (cover letter, recruiter summary, interview questions) that persist into the existing `generated_documents` table.

**Architecture:** Two new `GET` endpoints on the existing `sessions` router reformat already-persisted rows with no new DB writes. Three new service modules follow the exact dependency-guard-then-orchestrator-call shape established by `tailoring_engine.py`/`evaluator.py`/`document_generator.py`, wired into `STAGE_RUNNERS` the same way every stage since Phase 2 has been. Cover letter and recruiter summary reuse a fabrication guard extracted from `tailoring_engine.py` into a new shared module.

**Tech Stack:** FastAPI, SQLAlchemy, Pydantic, Jinja2 (prompt templates), pytest.

## Global Constraints

- New `generated_documents.document_type` values: `"cover_letter"`, `"recruiter_summary"`, `"interview_questions"`. All three populate `content` (text) and leave `storage_path` `None` — the reverse of Phase 7's PDF row.
- `version_number` scoping matches Phase 7's precedent exactly: `max(version_number for this session_id + document_type) + 1`, starting at 1.
- Cover letter and recruiter summary depend on `tailoring_rewrite` (the tailored `ResumeVersion`, looked up via `filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite").order_by(ResumeVersion.id.desc()).first()`) + `gap_analysis` (looked up via `filter_by(session_id=session.id).order_by(GapAnalysis.id.desc()).first()`) — identical query shape to `document_generator.py`/`tailoring_engine.py`.
- Interview questions depends on `jd_extraction` (`job_posting.parsed_json is not None`) + `gap_analysis` (same query as above).
- Every new stage's dependency guard must raise its dedicated error class **before** any orchestrator call — proven in tests via `orchestrator.calls == []`.
- `InterviewQuestionsDocument.questions` has `Field(min_length=5)` — this is the entire guard for that document type; no code-level content-quality heuristic.
- The cover-letter/recruiter-summary fabrication guard scans the ENTIRE generated `body` text (not a separately-LLM-reported claims list), tokenizing via the extracted `skill_matching.py` helper and checking every skill/technology-like token against the same "earned skills" set `tailoring_engine.py` already uses (resume's `skills` list + bullet/technology mentions + `gap_analysis.matching_skills`).
- Windows test runner for this repo: `.venv\Scripts\python.exe -m pytest` (or `py -3 -m pytest`), run from `backend/`.
- Baseline before Task 1: 192 passed, 2 skipped (per Phase 7's final state, in an environment without Tectonic — the Tectonic-gated test and the Postgres-gated migration test both skip).

---

### Task 1: Ledger Cleanup

**Files:**
- Modify: `backend/tests/test_jd_extractor.py`
- Modify: `backend/prompts/gap_analysis/v1.jinja2`
- Modify: `backend/tests/test_gap_analysis_prompt.py`
- Modify: `backend/prompts/tailoring_rewrite/v1.jinja2`
- Modify: `backend/tests/test_tailoring_prompt.py`

**Interfaces:** None — this task touches only prompt text and tests, no new functions/types.

This closes 4 of the 5 carried-forward ledger items with real fixes. The 5th (`cosmetic report-artifact text-garbling, doc-only`) is dropped as unfindable — it has been carried forward unchanged since Phase 3's final review without ever being pinned to a specific file or line, and a fresh targeted search (mojibake patterns, duplicated-word patterns, doc diffs across Phase 3/4) found nothing. Do not spend further time searching for it; note in your task report that it's being closed as unfindable, not silently dropped.

- [ ] **Step 1: Add the untested `Responsibilities:`/`Keywords:` extraction test**

In `backend/tests/test_jd_extractor.py`, change the fixture import (line 8-10) to also import `complete_jd_text`:

```python
from tests.fixtures.jd_fixtures import (
    blurred_requirements_qualifications_jd_text, not_a_job_posting_text, complete_jd_text,
)
```

Add this test at the end of the file:

```python
def test_extract_job_posting_persists_responsibilities_and_keywords():
    """Ledger cleanup (Phase 8 Task 1): complete_jd_text's Responsibilities:/
    Keywords: labeled sections were never previously exercised through the real
    extractor — every other test uses a fixture missing one or both sections.
    This closes the gap by asserting both fields persist correctly when both
    sections are genuinely present in the source text."""
    db = _make_db()
    job_posting = JobPosting(raw_text=complete_jd_text())
    db.add(job_posting)
    db.commit()

    parsed_document = JobPostingDocument(
        title="Senior Backend Engineer", company="Acme Corp", location="Remote (US)",
        employment_type="Full-time",
        requirements=[
            "5+ years of experience with Python or Go",
            "Experience with distributed systems and message queues",
            "Strong understanding of relational databases",
        ],
        responsibilities=[
            "Design and implement backend services for our core platform",
            "Participate in on-call rotation",
            "Collaborate with product and design teams",
        ],
        qualifications=[
            "Bachelor's degree in Computer Science or equivalent experience",
            "Experience mentoring junior engineers",
        ],
        keywords=["Python", "Go", "PostgreSQL", "Kafka", "distributed systems"],
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=parsed_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    result = extract_job_posting(db, job_posting, orchestrator, prompt_registry)

    assert result.parsed_json["responsibilities"] == [
        "Design and implement backend services for our core platform",
        "Participate in on-call rotation",
        "Collaborate with product and design teams",
    ]
    assert result.parsed_json["keywords"] == ["Python", "Go", "PostgreSQL", "Kafka", "distributed systems"]
```

- [ ] **Step 2: Run the new test to verify it passes**

Run (from `backend/`): `.venv\Scripts\python.exe -m pytest tests/test_jd_extractor.py -v`
Expected: 6 passed (5 existing + 1 new).

- [ ] **Step 3: Fix the gap-analysis strict-match rule's clause (a) qualifier**

In `backend/prompts/gap_analysis/v1.jinja2`, find:

```
CRITICAL RULE - Matching Skills: A skill counts as "matching" ONLY if:
(a) it is stated explicitly in the resume, OR
(b) it is an unambiguous synonym or abbreviation of a JD-required skill
    (e.g. "JS" <-> "JavaScript", "k8s" <-> "Kubernetes").
```

Replace with:

```
CRITICAL RULE - Matching Skills: A skill counts as "matching" ONLY if:
(a) it is stated explicitly in the resume - in its skills list, a work
    experience bullet, or a project's technologies - OR
(b) it is an unambiguous synonym or abbreviation of a JD-required skill
    (e.g. "JS" <-> "JavaScript", "k8s" <-> "Kubernetes").
```

- [ ] **Step 4: Add a prompt-quality test for the clause (a) qualifier**

Add to `backend/tests/test_gap_analysis_prompt.py`:

```python
def test_gap_analysis_prompt_clarifies_where_a_matching_skill_may_appear():
    """Ledger cleanup (Phase 8 Task 1): clause (a) of the strict-match rule
    previously read as a standalone sufficient condition with no qualifier on
    WHERE in the resume a skill must appear - this asserts the qualifier is
    genuinely present in the rendered prompt."""
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render("gap_analysis", "v1", resume_json="{}", job_posting_json="{}")
    lowered = rendered.lower()
    assert "skills list" in lowered
    assert "bullet" in lowered
    assert "technologies" in lowered
```

- [ ] **Step 5: Run the gap-analysis prompt tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_gap_analysis_prompt.py -v`
Expected: 6 passed (5 existing + 1 new).

- [ ] **Step 6: Fix the tailoring-rewrite metrics rule and add the override-ordering sentence**

In `backend/prompts/tailoring_rewrite/v1.jinja2`, find:

```
CRITICAL RULE - No Fabricated Metrics: Never invent a number, percentage, or
metric that is not already stated in the original resume below. For example:
```

Replace with:

```
CRITICAL RULE - No Fabricated Metrics: Never invent a number, percentage, or
metric that is not already stated in the original resume below. A number
appearing in the job posting or gap analysis below is NOT a valid source for
a metric about the candidate's own experience - it describes the role or the
comparison, not something the candidate has actually done. For example:
```

Then find:

```
CRITICAL RULE - Never Claim a Missing Skill: The gap analysis's
missing_skills list names skills the candidate does NOT have. NEVER
incorporate a missing_skill into the tailored resume as though the candidate
already possesses it. missing_skills exists to inform what NOT to claim, not
as a checklist of skills to add.
```

Replace with:

```
CRITICAL RULE - Never Claim a Missing Skill: The gap analysis's
missing_skills list names skills the candidate does NOT have. NEVER
incorporate a missing_skill into the tailored resume as though the candidate
already possesses it. missing_skills exists to inform what NOT to claim, not
as a checklist of skills to add. If a skill somehow appears in BOTH the
original resume/matching_skills AND missing_skills (an upstream data
inconsistency), this rule takes precedence over the No Unearned Skills rule
above: treat it as NOT claimable, and do not add it to the tailored resume.
```

- [ ] **Step 7: Add prompt-quality tests for both fixes**

Add to `backend/tests/test_tailoring_prompt.py`:

```python
def test_tailoring_prompt_forecloses_metrics_sourced_from_jd_or_gap_analysis():
    """Ledger cleanup (Phase 8 Task 1): the metrics rule previously only said
    'not already stated in the original resume', without explicitly ruling out
    lifting a number from the JD/gap-analysis JSON instead."""
    rendered = _render()
    lowered = rendered.lower()
    assert "job posting or gap analysis" in lowered
    assert "not a valid source" in lowered


def test_tailoring_prompt_states_missing_skill_precedence_over_unearned_skill_rule():
    """Ledger cleanup (Phase 8 Task 1): no explicit override-ordering was
    previously stated between the No Unearned Skills and Never Claim a Missing
    Skill rules for the both-traceable-and-missing edge case."""
    rendered = _render()
    lowered = rendered.lower()
    assert "takes precedence" in lowered
    assert "upstream data" in lowered or "inconsistency" in lowered
```

- [ ] **Step 8: Run the tailoring prompt tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tailoring_prompt.py -v`
Expected: 9 passed (7 existing + 2 new).

- [ ] **Step 9: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 196 passed, 2 skipped (192 baseline + 4 new tests from this task).

- [ ] **Step 10: Commit**

```bash
git add backend/tests/test_jd_extractor.py backend/prompts/gap_analysis/v1.jinja2 backend/tests/test_gap_analysis_prompt.py backend/prompts/tailoring_rewrite/v1.jinja2 backend/tests/test_tailoring_prompt.py
git commit -m "fix: close 3 ledger items (JD fixture coverage, strict-match qualifier, tailoring rule ordering/scope), drop 1 unfindable"
```

---

### Task 2: Shared Tokenizer Extraction

**Files:**
- Create: `backend/app/services/skill_matching.py`
- Modify: `backend/app/services/tailoring_engine.py`
- Test: `backend/tests/test_tailoring_engine.py` (no changes expected — this proves the refactor is behavior-preserving)

**Interfaces:**
- Produces: `skill_matching.tokenize_for_skill_matching(text: str) -> list[str]`, `skill_matching.skill_mentioned_in_token_groups(skill: str, token_groups: list[list[str]]) -> bool`, `skill_matching.collect_earned_skills(resume_json: dict, matching_skills: list[str]) -> tuple[set[str], list[list[str]]]`. Tasks 4/5 import all three from here.

This is a pure, behavior-preserving extraction: move the three private helpers out of `tailoring_engine.py` verbatim (dropping the leading underscore since they're now a public shared module's API), import them back into `tailoring_engine.py`, and verify every existing `tailoring_engine.py` test still passes unchanged.

- [ ] **Step 1: Create the shared module**

`backend/app/services/skill_matching.py`:

```python
import re

# Matches word-like chunks, keeping symbols that are part of common technology
# names attached to their letters (e.g. "C++", "C#", "Node.js") so a bare "C"
# or "Node" never matches as a substring of a different, more specific name.
_SKILL_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*")


def tokenize_for_skill_matching(text: str) -> list[str]:
    """Tokenize prose into word-like chunks for skill-matching purposes (see
    _SKILL_TOKEN_PATTERN)."""
    return _SKILL_TOKEN_PATTERN.findall(text)


def skill_mentioned_in_token_groups(skill: str, token_groups: list[list[str]]) -> bool:
    """True if `skill` is genuinely mentioned in `token_groups` - either as a
    standalone single-word technology name, or (for multi-word skills like
    "React Native") as the exact word sequence. Each group is the tokens of one
    bullet, kept separate so a skill at the end of one bullet is never treated
    as adjacent to the first (often-capitalized, sentence-initial) word of the
    next bullet.

    A single-word skill is NOT considered mentioned merely because it's the
    first word of an adjacent, differently-named two-word compound within the
    SAME bullet (e.g. "React" inside "React Native") unless it also appears on
    its own elsewhere - this is what prevents "Java" from matching inside
    "JavaScript" or "React" from matching inside "React Native" while still
    allowing genuine standalone mentions."""
    skill_tokens = skill.split()
    if not skill_tokens:
        return False

    if len(skill_tokens) == 1:
        skill_lower = skill_tokens[0].lower()
        for tokens in token_groups:
            for i, token in enumerate(tokens):
                if token.lower() != skill_lower:
                    continue
                next_token = tokens[i + 1] if i + 1 < len(tokens) else None
                if next_token is not None and next_token[:1].isupper():
                    # Immediately followed by another capitalized word within
                    # the SAME bullet - this occurrence could be the first
                    # half of a distinct two-word compound (e.g. "React" +
                    # "Native"); don't count it as a standalone mention, but
                    # keep looking for another occurrence.
                    continue
                return True
        return False

    skill_lower_tokens = [t.lower() for t in skill_tokens]
    n = len(skill_lower_tokens)
    for tokens in token_groups:
        for i in range(len(tokens) - n + 1):
            if [t.lower() for t in tokens[i:i + n]] == skill_lower_tokens:
                return True
    return False


def collect_earned_skills(resume_json: dict, matching_skills: list[str]) -> tuple[set[str], list[list[str]]]:
    """Return (earned_skill_strings, bullet_token_groups): the whitelist a
    code-level skills guard checks candidate skill mentions against, and the
    tokenized bullet prose (one token list per bullet) a skill can also be
    "earned" by appearing in (e.g. "Django" mentioned in a sentence but never
    listed in a dedicated skills/technologies field)."""
    earned = set(resume_json.get("skills", []))
    earned.update(matching_skills)
    bullet_texts = [
        bullet
        for entry in resume_json.get("work_experience", [])
        for bullet in entry.get("bullets", [])
    ]
    for project in resume_json.get("projects", []):
        earned.update(project.get("technologies", []))
        bullet_texts.extend(project.get("bullets", []))
    bullet_token_groups = [tokenize_for_skill_matching(bullet) for bullet in bullet_texts]
    return earned, bullet_token_groups
```

- [ ] **Step 2: Update `tailoring_engine.py` to import from the shared module**

In `backend/app/services/tailoring_engine.py`, remove the module-level `import re`, the `_SKILL_TOKEN_PATTERN` constant, and the `_tokenize_for_skill_matching`, `_skill_mentioned_in_token_groups`, and `_collect_earned_skills` function definitions (lines 2, 20-93 in the current file). Add this import near the top instead:

```python
from app.services.skill_matching import skill_mentioned_in_token_groups, collect_earned_skills
```

Update the two call sites that used the old private names. In `_find_unearned_skill`:

```python
def _find_unearned_skill(
    tailored_resume_json: dict, earned_skills: set[str], bullet_token_groups: list[list[str]]
) -> str | None:
    candidates = list(tailored_resume_json.get("skills", []))
    for project in tailored_resume_json.get("projects", []):
        candidates.extend(project.get("technologies", []))
    for skill in candidates:
        if skill in earned_skills or skill_mentioned_in_token_groups(skill, bullet_token_groups):
            continue
        return skill
    return None
```

In `tailor_resume`, the call to `_collect_earned_skills` becomes:

```python
    earned_skills, bullet_token_groups = collect_earned_skills(
        original_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
```

- [ ] **Step 3: Run the full `tailoring_engine.py` test suite to verify the refactor is behavior-preserving**

Run: `.venv\Scripts\python.exe -m pytest tests/test_tailoring_engine.py -v`
Expected: all 17 tests pass unchanged (same count and names as before this task — no test file edits were made).

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 196 passed, 2 skipped (no change in count from Task 1's end state — this task adds no new tests, per spec §7).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/skill_matching.py backend/app/services/tailoring_engine.py
git commit -m "refactor: extract skill-matching tokenizer into a shared module"
```

---

### Task 3: New Response Schemas

**Files:**
- Create: `backend/app/models/cover_letter.py`
- Create: `backend/app/models/recruiter_summary.py`
- Create: `backend/app/models/interview_questions.py`
- Test: `backend/tests/test_cover_letter_schema.py`
- Test: `backend/tests/test_recruiter_summary_schema.py`
- Test: `backend/tests/test_interview_questions_schema.py`

**Interfaces:**
- Produces: `CoverLetterDocument(schema_version: int, body: str)`, `RecruiterSummaryDocument(schema_version: int, body: str)`, `InterviewQuestionsDocument(schema_version: int, questions: list[str])` (min 5 items). Tasks 4/5/6 use these as `TaskConfig.response_schema`.

- [ ] **Step 1: Write the failing schema tests**

`backend/tests/test_cover_letter_schema.py`:

```python
import pytest
from app.models.cover_letter import (
    CoverLetterDocument,
    CURRENT_COVER_LETTER_SCHEMA_VERSION,
    migrate_cover_letter_document,
    UnsupportedCoverLetterSchemaVersion,
)


def test_cover_letter_document_defaults_to_current_schema_version():
    doc = CoverLetterDocument(body="Dear Hiring Manager, ...")
    assert doc.schema_version == CURRENT_COVER_LETTER_SCHEMA_VERSION
    assert doc.body == "Dear Hiring Manager, ..."


def test_cover_letter_document_roundtrips_through_json():
    doc = CoverLetterDocument(body="Dear Hiring Manager, I am writing to apply.")
    serialized = doc.model_dump_json()
    assert '"schema_version"' in serialized
    restored = CoverLetterDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_cover_letter_document_accepts_current_version():
    raw = {"schema_version": 1, "body": "Dear Hiring Manager, ..."}
    doc = migrate_cover_letter_document(raw)
    assert doc.body == "Dear Hiring Manager, ..."


def test_migrate_cover_letter_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "body": "..."}
    with pytest.raises(UnsupportedCoverLetterSchemaVersion):
        migrate_cover_letter_document(raw)
```

`backend/tests/test_recruiter_summary_schema.py`:

```python
import pytest
from app.models.recruiter_summary import (
    RecruiterSummaryDocument,
    CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION,
    migrate_recruiter_summary_document,
    UnsupportedRecruiterSummarySchemaVersion,
)


def test_recruiter_summary_document_defaults_to_current_schema_version():
    doc = RecruiterSummaryDocument(body="A strong backend candidate with...")
    assert doc.schema_version == CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION
    assert doc.body == "A strong backend candidate with..."


def test_recruiter_summary_document_roundtrips_through_json():
    doc = RecruiterSummaryDocument(body="A strong backend candidate.")
    serialized = doc.model_dump_json()
    assert '"schema_version"' in serialized
    restored = RecruiterSummaryDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_recruiter_summary_document_accepts_current_version():
    raw = {"schema_version": 1, "body": "A strong backend candidate."}
    doc = migrate_recruiter_summary_document(raw)
    assert doc.body == "A strong backend candidate."


def test_migrate_recruiter_summary_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "body": "..."}
    with pytest.raises(UnsupportedRecruiterSummarySchemaVersion):
        migrate_recruiter_summary_document(raw)
```

`backend/tests/test_interview_questions_schema.py`:

```python
import pytest
from pydantic import ValidationError
from app.models.interview_questions import (
    InterviewQuestionsDocument,
    CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION,
    migrate_interview_questions_document,
    UnsupportedInterviewQuestionsSchemaVersion,
)


def test_interview_questions_document_defaults_to_current_schema_version():
    doc = InterviewQuestionsDocument(questions=["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"])
    assert doc.schema_version == CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION
    assert len(doc.questions) == 5


def test_interview_questions_document_rejects_fewer_than_five_questions():
    """Structural-validation guard (spec §3, §7): min_length=5 is the entire
    guard for this document type - this proves it's actually enforced by
    Pydantic at construction time, not merely documented."""
    with pytest.raises(ValidationError):
        InterviewQuestionsDocument(questions=["Q1?", "Q2?", "Q3?", "Q4?"])


def test_interview_questions_document_roundtrips_through_json():
    doc = InterviewQuestionsDocument(questions=["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"])
    serialized = doc.model_dump_json()
    assert '"schema_version"' in serialized
    restored = InterviewQuestionsDocument.model_validate_json(serialized)
    assert restored == doc


def test_migrate_interview_questions_document_accepts_current_version():
    raw = {"schema_version": 1, "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]}
    doc = migrate_interview_questions_document(raw)
    assert len(doc.questions) == 5


def test_migrate_interview_questions_document_rejects_unknown_future_version():
    raw = {"schema_version": 999, "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]}
    with pytest.raises(UnsupportedInterviewQuestionsSchemaVersion):
        migrate_interview_questions_document(raw)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cover_letter_schema.py tests/test_recruiter_summary_schema.py tests/test_interview_questions_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models.cover_letter'` (and similarly for the other two).

- [ ] **Step 3: Write the three schema modules**

`backend/app/models/cover_letter.py`:

```python
from __future__ import annotations
from pydantic import BaseModel

CURRENT_COVER_LETTER_SCHEMA_VERSION = 1


class CoverLetterDocument(BaseModel):
    schema_version: int = CURRENT_COVER_LETTER_SCHEMA_VERSION
    body: str


class UnsupportedCoverLetterSchemaVersion(Exception):
    pass


def migrate_cover_letter_document(data: dict) -> CoverLetterDocument:
    """Load a raw generated_documents.content dict of any known schema_version
    into the current CoverLetterDocument shape. New migrators get registered
    here the first time schema_version is bumped past 1 - mirrors
    app/models/gap_analysis.py's migrate_gap_analysis_document."""
    version = data.get("schema_version", CURRENT_COVER_LETTER_SCHEMA_VERSION)
    if version == CURRENT_COVER_LETTER_SCHEMA_VERSION:
        return CoverLetterDocument.model_validate(data)
    raise UnsupportedCoverLetterSchemaVersion(
        f"No migrator registered for cover letter schema_version={version}"
    )
```

`backend/app/models/recruiter_summary.py`:

```python
from __future__ import annotations
from pydantic import BaseModel

CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION = 1


class RecruiterSummaryDocument(BaseModel):
    schema_version: int = CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION
    body: str


class UnsupportedRecruiterSummarySchemaVersion(Exception):
    pass


def migrate_recruiter_summary_document(data: dict) -> RecruiterSummaryDocument:
    """Load a raw generated_documents.content dict of any known schema_version
    into the current RecruiterSummaryDocument shape. New migrators get
    registered here the first time schema_version is bumped past 1 - mirrors
    app/models/gap_analysis.py's migrate_gap_analysis_document."""
    version = data.get("schema_version", CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION)
    if version == CURRENT_RECRUITER_SUMMARY_SCHEMA_VERSION:
        return RecruiterSummaryDocument.model_validate(data)
    raise UnsupportedRecruiterSummarySchemaVersion(
        f"No migrator registered for recruiter summary schema_version={version}"
    )
```

`backend/app/models/interview_questions.py`:

```python
from __future__ import annotations
from pydantic import BaseModel, Field

CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION = 1


class InterviewQuestionsDocument(BaseModel):
    schema_version: int = CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION
    questions: list[str] = Field(min_length=5)


class UnsupportedInterviewQuestionsSchemaVersion(Exception):
    pass


def migrate_interview_questions_document(data: dict) -> InterviewQuestionsDocument:
    """Load a raw generated_documents.content dict of any known schema_version
    into the current InterviewQuestionsDocument shape. New migrators get
    registered here the first time schema_version is bumped past 1 - mirrors
    app/models/gap_analysis.py's migrate_gap_analysis_document."""
    version = data.get("schema_version", CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION)
    if version == CURRENT_INTERVIEW_QUESTIONS_SCHEMA_VERSION:
        return InterviewQuestionsDocument.model_validate(data)
    raise UnsupportedInterviewQuestionsSchemaVersion(
        f"No migrator registered for interview questions schema_version={version}"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cover_letter_schema.py tests/test_recruiter_summary_schema.py tests/test_interview_questions_schema.py -v`
Expected: 13 passed (4 in test_cover_letter_schema.py + 4 in test_recruiter_summary_schema.py + 5 in test_interview_questions_schema.py — the extra test in the last file covers the min_length=5 rejection, which body:str has no equivalent of).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 209 passed, 2 skipped (196 + 13 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/cover_letter.py backend/app/models/recruiter_summary.py backend/app/models/interview_questions.py backend/tests/test_cover_letter_schema.py backend/tests/test_recruiter_summary_schema.py backend/tests/test_interview_questions_schema.py
git commit -m "feat: add CoverLetterDocument, RecruiterSummaryDocument, InterviewQuestionsDocument schemas"
```

---

### Task 4: Cover Letter Generator

**Files:**
- Create: `backend/prompts/cover_letter/v1.jinja2`
- Create: `backend/app/services/cover_letter_generator.py`
- Test: `backend/tests/test_cover_letter_prompt.py`
- Test: `backend/tests/test_cover_letter_generator.py`

**Interfaces:**
- Consumes: `collect_earned_skills`, `skill_mentioned_in_token_groups`, `tokenize_for_skill_matching` from `app.services.skill_matching` (Task 2). `CoverLetterDocument` from `app.models.cover_letter` (Task 3). `tests.fixtures.tailoring_fixtures.base_tailoring_triple` (existing fixture, reused as-is).
- Produces: `generate_cover_letter(db: Session, session: TailoringSession, orchestrator: AIOrchestrator, prompt_registry: PromptRegistry) -> GeneratedDocument`, `CoverLetterError(StageExecutionError)`. Task 7's dispatcher calls `generate_cover_letter`.

- [ ] **Step 1: Write the prompt template**

`backend/prompts/cover_letter/v1.jinja2`:

```
You are writing a cover letter on behalf of a candidate, for a specific job
posting, using their tailored resume and a gap analysis identifying which
skills genuinely match the role. Your job is to write persuasive, honest
prose - never to invent achievements, skills, or experience the candidate
does not actually have.

CRITICAL RULE - No Fabricated Skills or Technologies: Never mention a skill
or technology in the cover letter unless it already appears somewhere in the
candidate's resume below (its skills list, a work experience bullet, or a
project's technologies) OR in the gap analysis's matching_skills. For
example:

Resume skills: Python, Django
Gap analysis matching_skills: Python
WRONG: "I have extensive experience with Flask and other Python frameworks"
  (Flask was never in the resume or matching_skills - this is an unearned
  skill claim, even if Django and Flask are related frameworks)
CORRECT: "I have built and maintained production Django applications"
  (grounded in what the resume actually says)

CRITICAL RULE - No Fabricated Achievements or Metrics: Never invent a number,
percentage, achievement, or specific outcome that is not already stated in
the resume below. A number appearing in the job posting or gap analysis is
NOT a valid source for a claim about the candidate's own experience.

CRITICAL RULE - Never Claim a Missing Skill: The gap analysis's
missing_skills list names skills the candidate does NOT have. NEVER phrase
the cover letter as though the candidate already possesses a missing_skill.
It is acceptable to express genuine enthusiasm for growing into an area named
in missing_skills, but never claim existing proficiency in it.

Output ONLY a single JSON object matching exactly this shape (no markdown
code fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "body": "the full cover letter text, including salutation and closing"
}

Tailored resume (structured JSON):

{{ resume_json }}

Job posting (structured JSON):

{{ job_posting_json }}

Gap analysis (structured JSON):

{{ gap_analysis_json }}
```

- [ ] **Step 2: Write the failing prompt-quality tests**

`backend/tests/test_cover_letter_prompt.py`:

```python
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
```

- [ ] **Step 3: Run the prompt tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cover_letter_prompt.py -v`
Expected: FAIL with `jinja2.exceptions.TemplateNotFound` (the template already exists from Step 1, so this actually confirms Step 1's file path/name is correct — if it instead fails on an assertion, fix the template's wording to match).

- [ ] **Step 4: Run the prompt tests again to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cover_letter_prompt.py -v`
Expected: 5 passed.

- [ ] **Step 5: Write the failing service tests**

`backend/tests/test_cover_letter_generator.py`:

```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, GeneratedDocument,
)
from app.models.cover_letter import CoverLetterDocument
from app.services.cover_letter_generator import generate_cover_letter, CoverLetterError
from tests.fixtures.tailoring_fixtures import base_tailoring_triple


class FakeOrchestrator:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = []

    def run(self, task, prompt):
        self.calls.append((task, prompt))
        if self._error is not None:
            raise self._error
        return self._result


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_all_prerequisites(db, resume_json, job_posting_json, gap_analysis_json):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_json)
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json=resume_json, produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=tailored_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_json,
    )
    db.add(gap_analysis)
    db.commit()

    return session, tailored_version, job_posting, gap_analysis


def test_generate_cover_letter_persists_document_with_content():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(body="Dear Hiring Manager, I have built REST APIs using Python and Django.")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert document.session_id == session.id
    assert document.resume_version_id == tailored_version.id
    assert document.document_type == "cover_letter"
    assert document.storage_path is None
    assert document.content == "Dear Hiring Manager, I have built REST APIs using Python and Django."
    assert document.version_number == 1
    assert db.query(GeneratedDocument).count() == 1


def test_generate_cover_letter_fails_fast_when_no_tailored_version_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError, match="tailoring_rewrite"):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_cover_letter_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()
    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError, match="gap_analysis"):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_cover_letter_rejects_unearned_skill_and_persists_nothing():
    """Fabrication guard test (spec §4, §7): a generated cover letter claiming
    'Flask' when only 'Django' was in the original resume and gap analysis
    must be rejected outright - nothing persisted."""
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(
        body="Dear Hiring Manager, I have extensive experience with Flask and other frameworks."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError, match="Flask"):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0


def test_generate_cover_letter_accepts_earned_skill_mentioned_in_prose():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(
        body="Dear Hiring Manager, I have built production Django applications using PostgreSQL."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert "Django" in document.content


def test_generate_cover_letter_version_numbering_increments_within_session():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = CoverLetterDocument(body="Dear Hiring Manager, I have built production Django applications.")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_document = generate_cover_letter(db, session, orchestrator, prompt_registry)
    second_document = generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


def test_generate_cover_letter_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(CoverLetterError):
        generate_cover_letter(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0
```

- [ ] **Step 6: Run the service tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cover_letter_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.cover_letter_generator'`.

- [ ] **Step 7: Write the service**

The fabrication guard cannot scan every token in free-form prose against the earned-skills set — English prose is full of capitalized words, proper nouns, and common words that would false-positive as "unearned skills" (e.g. "Dear", "Hiring", "Manager"). Instead, the guard only checks tokens that plausibly look like a skill/technology name: **capitalized non-sentence-initial tokens**, since real skill names in generated prose are almost always proper nouns or capitalized technology names (Python, Django, PostgreSQL), and checking every word would make the guard reject a letter for containing "Manager" or "Dear".

`backend/app/services/cover_letter_generator.py`:

```python
import json
import re
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis, GeneratedDocument
from app.models.cover_letter import CoverLetterDocument
from app.services.errors import StageExecutionError
from app.services.skill_matching import (
    collect_earned_skills, skill_mentioned_in_token_groups, tokenize_for_skill_matching,
)

COVER_LETTER_MODEL = "z-ai/glm-5.2"
COVER_LETTER_TEMPERATURE = 0.1
DOCUMENT_TYPE = "cover_letter"

# A capitalized token that is NOT the first word of its sentence is treated as
# a candidate skill/technology mention (e.g. "Django" mid-sentence) - this
# excludes ordinary sentence-initial capitalization ("Dear", "I") from being
# checked against the earned-skills whitelist, since checking every
# capitalized word would reject a letter for containing "Manager" or "Dear".
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")


class CoverLetterError(StageExecutionError):
    """Raised when cover letter generation fails: unmet prerequisite stages,
    LLM-structuring failure, or a fabrication-guard rejection (an unearned
    skill mentioned in the generated prose)."""


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def _candidate_skill_tokens(body: str) -> list[str]:
    """Return capitalized tokens that are NOT the first word of a sentence -
    these are the candidates the guard checks against the earned-skills set."""
    sentences = _SENTENCE_BOUNDARY_PATTERN.split(body)
    candidates: list[str] = []
    for sentence in sentences:
        tokens = tokenize_for_skill_matching(sentence)
        for token in tokens[1:]:
            if token[:1].isupper():
                candidates.append(token)
    return candidates


def _find_unearned_skill_in_prose(
    body: str, earned_skills: set[str], bullet_token_groups: list[list[str]]
) -> str | None:
    earned_lower = {skill.lower() for skill in earned_skills}
    for candidate in _candidate_skill_tokens(body):
        if candidate.lower() in earned_lower:
            continue
        if skill_mentioned_in_token_groups(candidate, bullet_token_groups):
            continue
        return candidate
    return None


def generate_cover_letter(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GeneratedDocument:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise CoverLetterError("tailoring_rewrite has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise CoverLetterError("gap_analysis has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)

    prompt = prompt_registry.render(
        "cover_letter", "v1",
        resume_json=json.dumps(tailored_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="cover_letter",
        provider="nvidia",
        model=COVER_LETTER_MODEL,
        temperature=COVER_LETTER_TEMPERATURE,
        response_schema=CoverLetterDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise CoverLetterError(str(exc)) from exc

    body = result.output.body

    earned_skills, bullet_token_groups = collect_earned_skills(
        tailored_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
    unearned_skill = _find_unearned_skill_in_prose(body, earned_skills, bullet_token_groups)
    if unearned_skill is not None:
        raise CoverLetterError(
            f"generated cover letter mentions an unearned skill not present in the tailored "
            f"resume or gap analysis matching_skills: {unearned_skill!r}"
        )

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        document_type=DOCUMENT_TYPE,
        storage_path=None,
        content=body,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
```

- [ ] **Step 8: Run the service tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_cover_letter_generator.py -v`
Expected: 7 passed. If `test_generate_cover_letter_rejects_unearned_skill_and_persists_nothing` fails because "Flask" wasn't flagged, double check `_candidate_skill_tokens` is correctly excluding only the true first token of each sentence (index 0), not accidentally excluding "Flask" because it's the first word of a sentence in the fixture body — the fixture body above places "Flask" mid-sentence ("I have extensive experience with Flask and other frameworks"), so this should pass as written.

- [ ] **Step 9: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 221 passed, 2 skipped (209 + 5 prompt tests + 7 service tests = 221).

- [ ] **Step 10: Commit**

```bash
git add backend/prompts/cover_letter/v1.jinja2 backend/app/services/cover_letter_generator.py backend/tests/test_cover_letter_prompt.py backend/tests/test_cover_letter_generator.py
git commit -m "feat: add cover letter generator with prose-scanning fabrication guard"
```

---

### Task 5: Recruiter Summary Generator

**Files:**
- Create: `backend/prompts/recruiter_summary/v1.jinja2`
- Create: `backend/app/services/recruiter_summary_generator.py`
- Test: `backend/tests/test_recruiter_summary_prompt.py`
- Test: `backend/tests/test_recruiter_summary_generator.py`

**Interfaces:**
- Consumes: same as Task 4 (`skill_matching.py`, `RecruiterSummaryDocument` from Task 3, `base_tailoring_triple`).
- Produces: `generate_recruiter_summary(db, session, orchestrator, prompt_registry) -> GeneratedDocument`, `RecruiterSummaryError(StageExecutionError)`. Task 7's dispatcher calls `generate_recruiter_summary`.

This task is structurally identical to Task 4 — same dependency guard, same fabrication-guard mechanics, different prompt framing (third-person, recruiter-facing) and error class name.

- [ ] **Step 1: Write the prompt template**

`backend/prompts/recruiter_summary/v1.jinja2`:

```
You are writing a third-person recruiter-facing summary of a candidate, for a
specific job posting, using their tailored resume and a gap analysis
identifying which skills genuinely match the role. Your job is to summarize
the candidate's fit objectively and honestly - never to invent achievements,
skills, or experience the candidate does not actually have.

CRITICAL RULE - No Fabricated Skills or Technologies: Never mention a skill
or technology in the summary unless it already appears somewhere in the
candidate's resume below (its skills list, a work experience bullet, or a
project's technologies) OR in the gap analysis's matching_skills. For
example:

Resume skills: Python, Django
Gap analysis matching_skills: Python
WRONG: "The candidate has extensive experience with Flask and other Python
  frameworks" (Flask was never in the resume or matching_skills - this is an
  unearned skill claim, even if Django and Flask are related frameworks)
CORRECT: "The candidate has built and maintained production Django
  applications" (grounded in what the resume actually says)

CRITICAL RULE - No Fabricated Achievements or Metrics: Never invent a number,
percentage, achievement, or specific outcome that is not already stated in
the resume below. A number appearing in the job posting or gap analysis is
NOT a valid source for a claim about the candidate's own experience.

CRITICAL RULE - Never Claim a Missing Skill: The gap analysis's
missing_skills list names skills the candidate does NOT have. NEVER phrase
the summary as though the candidate already possesses a missing_skill. It is
acceptable to note a missing_skill as a genuine gap for the recruiter's
awareness, but never as an existing strength.

Output ONLY a single JSON object matching exactly this shape (no markdown
code fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "body": "the full recruiter-facing summary text"
}

Tailored resume (structured JSON):

{{ resume_json }}

Job posting (structured JSON):

{{ job_posting_json }}

Gap analysis (structured JSON):

{{ gap_analysis_json }}
```

- [ ] **Step 2: Write the failing prompt-quality tests**

`backend/tests/test_recruiter_summary_prompt.py`:

```python
from app.core.llm.prompt_registry import PromptRegistry
from app.core.db import make_engine, make_session_factory
from app.models.db_models import Base, PromptVersion


def _render():
    registry = PromptRegistry(prompts_root="prompts")
    return registry.render(
        "recruiter_summary", "v1",
        resume_json="{}", job_posting_json="{}", gap_analysis_json="{}",
    )


def test_recruiter_summary_prompt_registers_via_sync_to_db():
    registry = PromptRegistry(prompts_root="prompts")
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionFactory = make_session_factory(engine)

    with SessionFactory() as db:
        registry.sync_to_db(db)
        row = db.query(PromptVersion).filter_by(task_type="recruiter_summary", version="v1").one()
        assert row.template_path == "recruiter_summary/v1.jinja2"


def test_recruiter_summary_prompt_instructs_against_unearned_skills():
    rendered = _render()
    lowered = rendered.lower()
    assert "flask" in lowered
    assert "matching_skills" in rendered


def test_recruiter_summary_prompt_instructs_against_claiming_missing_skills():
    rendered = _render()
    lowered = rendered.lower()
    assert "missing_skills" in rendered
    assert "not" in lowered


def test_recruiter_summary_prompt_instructs_against_fabricated_metrics():
    rendered = _render()
    lowered = rendered.lower()
    assert "fabricat" in lowered or "invent" in lowered


def test_recruiter_summary_prompt_is_third_person():
    rendered = _render()
    lowered = rendered.lower()
    assert "third-person" in lowered
    assert "the candidate" in lowered


def test_recruiter_summary_prompt_embeds_all_three_input_documents():
    registry = PromptRegistry(prompts_root="prompts")
    rendered = registry.render(
        "recruiter_summary", "v1",
        resume_json='{"skills": ["Python"]}',
        job_posting_json='{"title": "Backend Engineer"}',
        gap_analysis_json='{"missing_skills": ["Docker"]}',
    )
    assert '{"skills": ["Python"]}' in rendered
    assert '{"title": "Backend Engineer"}' in rendered
    assert '{"missing_skills": ["Docker"]}' in rendered
```

- [ ] **Step 3: Run the prompt tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_recruiter_summary_prompt.py -v`
Expected: 6 passed.

- [ ] **Step 4: Write the failing service tests**

`backend/tests/test_recruiter_summary_generator.py` (identical structure to `test_cover_letter_generator.py`, adjusted names):

```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import (
    Base, Resume, ResumeVersion, JobPosting, TailoringSession, GapAnalysis, GeneratedDocument,
)
from app.models.recruiter_summary import RecruiterSummaryDocument
from app.services.recruiter_summary_generator import generate_recruiter_summary, RecruiterSummaryError
from tests.fixtures.tailoring_fixtures import base_tailoring_triple


class FakeOrchestrator:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = []

    def run(self, task, prompt):
        self.calls.append((task, prompt))
        if self._error is not None:
            raise self._error
        return self._result


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_all_prerequisites(db, resume_json, job_posting_json, gap_analysis_json):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=job_posting_json)
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json=resume_json, produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=tailored_version.id, job_posting_id=job_posting.id,
        analysis_json=gap_analysis_json,
    )
    db.add(gap_analysis)
    db.commit()

    return session, tailored_version, job_posting, gap_analysis


def test_generate_recruiter_summary_persists_document_with_content():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = RecruiterSummaryDocument(body="The candidate has built REST APIs using Python and Django.")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert document.session_id == session.id
    assert document.resume_version_id == tailored_version.id
    assert document.document_type == "recruiter_summary"
    assert document.storage_path is None
    assert document.content == "The candidate has built REST APIs using Python and Django."
    assert document.version_number == 1
    assert db.query(GeneratedDocument).count() == 1


def test_generate_recruiter_summary_fails_fast_when_no_tailored_version_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(RecruiterSummaryError, match="tailoring_rewrite"):
        generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_recruiter_summary_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()
    tailored_version = ResumeVersion(
        resume_id=resume.id, session_id=session.id, version_number=2,
        resume_json={"schema_version": 1, "contact": {"full_name": "Sam"}},
        produced_by_stage="tailoring_rewrite",
    )
    db.add(tailored_version)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(RecruiterSummaryError, match="gap_analysis"):
        generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_recruiter_summary_rejects_unearned_skill_and_persists_nothing():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = RecruiterSummaryDocument(
        body="The candidate has extensive experience with Flask and other frameworks."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(RecruiterSummaryError, match="Flask"):
        generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0


def test_generate_recruiter_summary_accepts_earned_skill_mentioned_in_prose():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = RecruiterSummaryDocument(
        body="The candidate has built production Django applications using PostgreSQL."
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert "Django" in document.content


def test_generate_recruiter_summary_version_numbering_increments_within_session():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    result_document = RecruiterSummaryDocument(body="The candidate has built production Django applications.")
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_document = generate_recruiter_summary(db, session, orchestrator, prompt_registry)
    second_document = generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


def test_generate_recruiter_summary_wraps_orchestrator_error():
    db = _make_db()
    resume_doc, job_posting_doc, gap_analysis_doc = base_tailoring_triple()
    session, tailored_version, job_posting, gap_analysis = _make_session_with_all_prerequisites(
        db, resume_doc.model_dump(), job_posting_doc.model_dump(), gap_analysis_doc.model_dump(),
    )

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(RecruiterSummaryError):
        generate_recruiter_summary(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0
```

- [ ] **Step 5: Run the service tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_recruiter_summary_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.recruiter_summary_generator'`.

- [ ] **Step 6: Write the service**

`backend/app/services/recruiter_summary_generator.py` (identical structure to the final `cover_letter_generator.py` from Task 4, with names swapped):

```python
import json
import re
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, ResumeVersion, GapAnalysis, GeneratedDocument
from app.models.recruiter_summary import RecruiterSummaryDocument
from app.services.errors import StageExecutionError
from app.services.skill_matching import (
    collect_earned_skills, skill_mentioned_in_token_groups, tokenize_for_skill_matching,
)

RECRUITER_SUMMARY_MODEL = "z-ai/glm-5.2"
RECRUITER_SUMMARY_TEMPERATURE = 0.1
DOCUMENT_TYPE = "recruiter_summary"

_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?])\s+")


class RecruiterSummaryError(StageExecutionError):
    """Raised when recruiter summary generation fails: unmet prerequisite
    stages, LLM-structuring failure, or a fabrication-guard rejection (an
    unearned skill mentioned in the generated prose)."""


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def _candidate_skill_tokens(body: str) -> list[str]:
    sentences = _SENTENCE_BOUNDARY_PATTERN.split(body)
    candidates: list[str] = []
    for sentence in sentences:
        tokens = tokenize_for_skill_matching(sentence)
        for token in tokens[1:]:
            if token[:1].isupper():
                candidates.append(token)
    return candidates


def _find_unearned_skill_in_prose(
    body: str, earned_skills: set[str], bullet_token_groups: list[list[str]]
) -> str | None:
    earned_lower = {skill.lower() for skill in earned_skills}
    for candidate in _candidate_skill_tokens(body):
        if candidate.lower() in earned_lower:
            continue
        if skill_mentioned_in_token_groups(candidate, bullet_token_groups):
            continue
        return candidate
    return None


def generate_recruiter_summary(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GeneratedDocument:
    tailored_version = (
        db.query(ResumeVersion)
        .filter_by(session_id=session.id, produced_by_stage="tailoring_rewrite")
        .order_by(ResumeVersion.id.desc())
        .first()
    )
    if tailored_version is None:
        raise RecruiterSummaryError("tailoring_rewrite has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise RecruiterSummaryError("gap_analysis has not succeeded for this session yet")

    job_posting = db.get(JobPosting, session.job_posting_id)

    prompt = prompt_registry.render(
        "recruiter_summary", "v1",
        resume_json=json.dumps(tailored_version.resume_json, indent=2),
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="recruiter_summary",
        provider="nvidia",
        model=RECRUITER_SUMMARY_MODEL,
        temperature=RECRUITER_SUMMARY_TEMPERATURE,
        response_schema=RecruiterSummaryDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise RecruiterSummaryError(str(exc)) from exc

    body = result.output.body

    earned_skills, bullet_token_groups = collect_earned_skills(
        tailored_version.resume_json, gap_analysis.analysis_json.get("matching_skills", [])
    )
    unearned_skill = _find_unearned_skill_in_prose(body, earned_skills, bullet_token_groups)
    if unearned_skill is not None:
        raise RecruiterSummaryError(
            f"generated recruiter summary mentions an unearned skill not present in the tailored "
            f"resume or gap analysis matching_skills: {unearned_skill!r}"
        )

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=tailored_version.id,
        document_type=DOCUMENT_TYPE,
        storage_path=None,
        content=body,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
```

- [ ] **Step 7: Run the service tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_recruiter_summary_generator.py -v`
Expected: 7 passed.

- [ ] **Step 8: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 234 passed, 2 skipped (221 + 6 prompt tests + 7 service tests = 234).

- [ ] **Step 9: Commit**

```bash
git add backend/prompts/recruiter_summary/v1.jinja2 backend/app/services/recruiter_summary_generator.py backend/tests/test_recruiter_summary_prompt.py backend/tests/test_recruiter_summary_generator.py
git commit -m "feat: add recruiter summary generator with prose-scanning fabrication guard"
```

---

### Task 6: Interview Questions Generator

**Files:**
- Create: `backend/prompts/interview_questions/v1.jinja2`
- Create: `backend/app/services/interview_questions_generator.py`
- Test: `backend/tests/test_interview_questions_prompt.py`
- Test: `backend/tests/test_interview_questions_generator.py`

**Interfaces:**
- Consumes: `InterviewQuestionsDocument` from `app.models.interview_questions` (Task 3).
- Produces: `generate_interview_questions(db, session, orchestrator, prompt_registry) -> GeneratedDocument`, `InterviewQuestionsError(StageExecutionError)`. Task 7's dispatcher calls `generate_interview_questions`.

- [ ] **Step 1: Write the prompt template**

`backend/prompts/interview_questions/v1.jinja2`:

```
You are generating interview questions for a hiring team, based on a job
posting and a gap analysis comparing a specific candidate's resume against
that posting. Generate at least 5 questions: a mix of role-relevant
questions grounded in the job posting's actual requirements and
responsibilities, and a few questions specifically probing the gap areas
named in the gap analysis's missing_skills or experience_gap_notes.

Do not generate generic filler questions unrelated to this specific role
(e.g. "Tell me about yourself") - every question should be traceable to
either the job posting's content or the gap analysis's findings below.

Output ONLY a single JSON object matching exactly this shape (no markdown
code fences, no explanation, no extra text before or after the JSON):

{
  "schema_version": 1,
  "questions": ["array of at least 5 question strings"]
}

Job posting (structured JSON):

{{ job_posting_json }}

Gap analysis (structured JSON):

{{ gap_analysis_json }}
```

- [ ] **Step 2: Write the failing prompt-quality tests**

`backend/tests/test_interview_questions_prompt.py`:

```python
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
```

- [ ] **Step 3: Run the prompt tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_interview_questions_prompt.py -v`
Expected: 5 passed.

- [ ] **Step 4: Write the failing service tests**

`backend/tests/test_interview_questions_generator.py`:

```python
import pytest
from app.core.db import make_engine, make_session_factory
from app.core.llm.orchestrator import OrchestratorResult, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import Base, JobPosting, TailoringSession, GapAnalysis, Resume, GeneratedDocument
from app.models.interview_questions import InterviewQuestionsDocument
from app.services.interview_questions_generator import generate_interview_questions, InterviewQuestionsError


class FakeOrchestrator:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = []

    def run(self, task, prompt):
        self.calls.append((task, prompt))
        if self._error is not None:
            raise self._error
        return self._result


def _make_db():
    engine = make_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)()


def _make_session_with_all_prerequisites(db):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()

    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    gap_analysis = GapAnalysis(
        session_id=session.id, resume_version_id=None, job_posting_id=job_posting.id,
        analysis_json={"missing_skills": ["Docker"]},
    )
    db.add(gap_analysis)
    db.commit()

    return session, job_posting, gap_analysis


def test_generate_interview_questions_persists_document_with_content():
    db = _make_db()
    session, job_posting, gap_analysis = _make_session_with_all_prerequisites(db)

    result_document = InterviewQuestionsDocument(
        questions=[
            "Can you walk me through your experience with Docker?",
            "How do you approach designing a REST API?",
            "Tell me about a time you debugged a production issue.",
            "How do you handle database migrations safely?",
            "What's your experience with distributed systems?",
        ]
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    document = generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert document.session_id == session.id
    assert document.document_type == "interview_questions"
    assert document.storage_path is None
    assert "Docker" in document.content
    assert document.version_number == 1
    assert db.query(GeneratedDocument).count() == 1


def test_generate_interview_questions_fails_fast_when_no_parsed_jd_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json=None)
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(InterviewQuestionsError, match="jd_extraction"):
        generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_interview_questions_fails_fast_when_gap_analysis_missing_without_calling_orchestrator():
    db = _make_db()
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job_posting = JobPosting(raw_text="placeholder", parsed_json={"title": "Backend Engineer"})
    db.add_all([resume, job_posting])
    db.commit()
    session = TailoringSession(resume_id=resume.id, job_posting_id=job_posting.id, status="created")
    db.add(session)
    db.commit()

    orchestrator = FakeOrchestrator()
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(InterviewQuestionsError, match="gap_analysis"):
        generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert orchestrator.calls == []


def test_generate_interview_questions_version_numbering_increments_within_session():
    db = _make_db()
    session, job_posting, gap_analysis = _make_session_with_all_prerequisites(db)

    result_document = InterviewQuestionsDocument(
        questions=["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"]
    )
    orchestrator = FakeOrchestrator(result=OrchestratorResult(output=result_document, provider_used="nvidia", attempts=1))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    first_document = generate_interview_questions(db, session, orchestrator, prompt_registry)
    second_document = generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert first_document.version_number == 1
    assert second_document.version_number == 2


def test_generate_interview_questions_wraps_orchestrator_error():
    """Structural-validation failures (e.g. fewer than 5 questions) surface as
    an OrchestratorError once every provider attempt has failed Pydantic
    validation - this proves the service wraps that as InterviewQuestionsError,
    the same way every other stage wraps an exhausted orchestrator."""
    db = _make_db()
    session, job_posting, gap_analysis = _make_session_with_all_prerequisites(db)

    orchestrator = FakeOrchestrator(error=OrchestratorError("all providers exhausted"))
    prompt_registry = PromptRegistry(prompts_root="prompts")

    with pytest.raises(InterviewQuestionsError):
        generate_interview_questions(db, session, orchestrator, prompt_registry)

    assert db.query(GeneratedDocument).count() == 0
```

- [ ] **Step 5: Run the service tests to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_interview_questions_generator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.services.interview_questions_generator'`.

- [ ] **Step 6: Write the service**

`backend/app/services/interview_questions_generator.py`:

```python
import json
from sqlalchemy.orm import Session
from app.core.llm.orchestrator import AIOrchestrator, TaskConfig, OrchestratorError
from app.core.llm.prompt_registry import PromptRegistry
from app.models.db_models import TailoringSession, JobPosting, GapAnalysis, GeneratedDocument
from app.models.interview_questions import InterviewQuestionsDocument
from app.services.errors import StageExecutionError

INTERVIEW_QUESTIONS_MODEL = "z-ai/glm-5.2"
INTERVIEW_QUESTIONS_TEMPERATURE = 0.3
DOCUMENT_TYPE = "interview_questions"


class InterviewQuestionsError(StageExecutionError):
    """Raised when interview question generation fails: unmet prerequisite
    stages, or LLM-structuring/validation failure (including fewer than the
    required minimum of 5 questions, enforced by InterviewQuestionsDocument's
    min_length constraint)."""


def _next_version_number(db: Session, session_id: int, document_type: str) -> int:
    latest = (
        db.query(GeneratedDocument)
        .filter_by(session_id=session_id, document_type=document_type)
        .order_by(GeneratedDocument.version_number.desc())
        .first()
    )
    return (latest.version_number if latest else 0) + 1


def generate_interview_questions(
    db: Session,
    session: TailoringSession,
    orchestrator: AIOrchestrator,
    prompt_registry: PromptRegistry,
) -> GeneratedDocument:
    job_posting = db.get(JobPosting, session.job_posting_id)
    if job_posting is None or job_posting.parsed_json is None:
        raise InterviewQuestionsError("jd_extraction has not succeeded for this session yet")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session.id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise InterviewQuestionsError("gap_analysis has not succeeded for this session yet")

    prompt = prompt_registry.render(
        "interview_questions", "v1",
        job_posting_json=json.dumps(job_posting.parsed_json, indent=2),
        gap_analysis_json=json.dumps(gap_analysis.analysis_json, indent=2),
    )
    task = TaskConfig(
        task_type="interview_questions",
        provider="nvidia",
        model=INTERVIEW_QUESTIONS_MODEL,
        temperature=INTERVIEW_QUESTIONS_TEMPERATURE,
        response_schema=InterviewQuestionsDocument,
        fallback_providers=[],
    )

    try:
        result = orchestrator.run(task, prompt=prompt)
    except OrchestratorError as exc:
        raise InterviewQuestionsError(str(exc)) from exc

    content = "\n".join(result.output.questions)

    version_number = _next_version_number(db, session.id, DOCUMENT_TYPE)
    document = GeneratedDocument(
        session_id=session.id,
        resume_version_id=None,
        document_type=DOCUMENT_TYPE,
        storage_path=None,
        content=content,
        version_number=version_number,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
```

- [ ] **Step 7: Run the service tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_interview_questions_generator.py -v`
Expected: 5 passed.

- [ ] **Step 8: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 244 passed, 2 skipped (234 + 5 prompt tests + 5 service tests = 244).

- [ ] **Step 9: Commit**

```bash
git add backend/prompts/interview_questions/v1.jinja2 backend/app/services/interview_questions_generator.py backend/tests/test_interview_questions_prompt.py backend/tests/test_interview_questions_generator.py
git commit -m "feat: add interview questions generator with structural validation guard"
```

---

### Task 7: Wire New Stages into `run_stage`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Consumes: `generate_cover_letter` (Task 4), `generate_recruiter_summary` (Task 5), `generate_interview_questions` (Task 6).
- Produces: `STAGE_RUNNERS["cover_letter"]`, `STAGE_RUNNERS["recruiter_summary"]`, `STAGE_RUNNERS["interview_questions"]`. No new interfaces later tasks depend on.

- [ ] **Step 1: Retarget the stale 501 test**

In `backend/tests/test_api_sessions.py`, `test_run_stage_returns_501_for_unimplemented_stage` (around line 21-31) currently posts to `cover_letter_generation` as its example of a not-yet-implemented stage. This phase implements `cover_letter` for real, so retarget it to a new, still-genuinely-unimplemented placeholder name:

```python
def test_run_stage_returns_501_for_unimplemented_stage(client, db_session):
    resume = Resume(original_filename="jane.pdf", storage_path="/tmp/jane.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.post(f"/sessions/{session_id}/run-stage/final_export")

    assert response.status_code == 501
```

- [ ] **Step 2: Add the three dispatcher functions and register them**

In `backend/app/api/sessions.py`, add these imports near the top (alongside the existing service imports):

```python
from app.services.cover_letter_generator import generate_cover_letter
from app.services.recruiter_summary_generator import generate_recruiter_summary
from app.services.interview_questions_generator import generate_interview_questions
```

Add these three dispatcher functions, placed after `_run_document_generation` and before the `STAGE_RUNNERS` dict:

```python
def _run_cover_letter(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    document = generate_cover_letter(db, session, orchestrator, prompt_registry)
    return {"generated_document_id": document.id}


def _run_recruiter_summary(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    document = generate_recruiter_summary(db, session, orchestrator, prompt_registry)
    return {"generated_document_id": document.id}


def _run_interview_questions(db: Session, session: TailoringSession, settings) -> dict:
    orchestrator = build_orchestrator(db, session_id=session.id)
    prompt_registry = PromptRegistry(prompts_root=settings.prompts_root)
    document = generate_interview_questions(db, session, orchestrator, prompt_registry)
    return {"generated_document_id": document.id}
```

Update `STAGE_RUNNERS` to:

```python
STAGE_RUNNERS = {
    "resume_parsing": _run_resume_parsing,
    "jd_extraction": _run_jd_extraction,
    "gap_analysis": _run_gap_analysis,
    "tailoring_rewrite": _run_tailoring,
    "evaluation": _run_evaluation,
    "document_generation": _run_document_generation,
    "cover_letter": _run_cover_letter,
    "recruiter_summary": _run_recruiter_summary,
    "interview_questions": _run_interview_questions,
}
```

- [ ] **Step 3: Write the API integration tests for all three new stages**

Add to `backend/tests/test_api_sessions.py`:

```python
def test_run_stage_cover_letter_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def fake_generate_cover_letter(db, session, orchestrator, prompt_registry):
        return FakeGeneratedDocument(id=11)

    monkeypatch.setattr(sessions_module, "generate_cover_letter", fake_generate_cover_letter)

    response = client.post(f"/sessions/{session_id}/run-stage/cover_letter")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "cover_letter", "status": "succeeded", "generated_document_id": 11}

    status_response = client.get(f"/sessions/{session_id}/status")
    runs = status_response.json()["pipeline_runs"]
    assert runs[0]["stage_name"] == "cover_letter"
    assert runs[0]["status"] == "succeeded"


def test_run_stage_cover_letter_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.cover_letter_generator import CoverLetterError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_generate_cover_letter(db, session, orchestrator, prompt_registry):
        raise CoverLetterError("tailoring_rewrite has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "generate_cover_letter", failing_generate_cover_letter)

    response = client.post(f"/sessions/{session_id}/run-stage/cover_letter")

    assert response.status_code == 422
    status_response = client.get(f"/sessions/{session_id}/status")
    assert status_response.json()["pipeline_runs"][0]["status"] == "failed"


def test_run_stage_cover_letter_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def slow_generate_cover_letter(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeGeneratedDocument(id=1)

    monkeypatch.setattr(sessions_module, "generate_cover_letter", slow_generate_cover_letter)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/cover_letter")

    assert response.status_code == 504
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    assert status_response.json()["pipeline_runs"][0]["status"] == "failed"


def test_run_stage_recruiter_summary_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def fake_generate_recruiter_summary(db, session, orchestrator, prompt_registry):
        return FakeGeneratedDocument(id=12)

    monkeypatch.setattr(sessions_module, "generate_recruiter_summary", fake_generate_recruiter_summary)

    response = client.post(f"/sessions/{session_id}/run-stage/recruiter_summary")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "recruiter_summary", "status": "succeeded", "generated_document_id": 12}


def test_run_stage_recruiter_summary_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.recruiter_summary_generator import RecruiterSummaryError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_generate_recruiter_summary(db, session, orchestrator, prompt_registry):
        raise RecruiterSummaryError("gap_analysis has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "generate_recruiter_summary", failing_generate_recruiter_summary)

    response = client.post(f"/sessions/{session_id}/run-stage/recruiter_summary")

    assert response.status_code == 422


def test_run_stage_recruiter_summary_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def slow_generate_recruiter_summary(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeGeneratedDocument(id=1)

    monkeypatch.setattr(sessions_module, "generate_recruiter_summary", slow_generate_recruiter_summary)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/recruiter_summary")

    assert response.status_code == 504
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    assert status_response.json()["pipeline_runs"][0]["status"] == "failed"


def test_run_stage_interview_questions_succeeds(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def fake_generate_interview_questions(db, session, orchestrator, prompt_registry):
        return FakeGeneratedDocument(id=13)

    monkeypatch.setattr(sessions_module, "generate_interview_questions", fake_generate_interview_questions)

    response = client.post(f"/sessions/{session_id}/run-stage/interview_questions")

    assert response.status_code == 200
    assert response.json() == {"stage_name": "interview_questions", "status": "succeeded", "generated_document_id": 13}


def test_run_stage_interview_questions_reports_failure(client, db_session, monkeypatch):
    import app.api.sessions as sessions_module
    from app.services.interview_questions_generator import InterviewQuestionsError

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    def failing_generate_interview_questions(db, session, orchestrator, prompt_registry):
        raise InterviewQuestionsError("jd_extraction has not succeeded for this session yet")

    monkeypatch.setattr(sessions_module, "generate_interview_questions", failing_generate_interview_questions)

    response = client.post(f"/sessions/{session_id}/run-stage/interview_questions")

    assert response.status_code == 422


def test_run_stage_interview_questions_times_out(client, db_session, monkeypatch):
    import time
    import app.api.sessions as sessions_module

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    class FakeGeneratedDocument:
        def __init__(self, id):
            self.id = id

    def slow_generate_interview_questions(db, session, orchestrator, prompt_registry):
        time.sleep(0.5)
        return FakeGeneratedDocument(id=1)

    monkeypatch.setattr(sessions_module, "generate_interview_questions", slow_generate_interview_questions)
    monkeypatch.setattr(sessions_module, "STAGE_TIMEOUT_SECONDS", 0.05)

    response = client.post(f"/sessions/{session_id}/run-stage/interview_questions")

    assert response.status_code == 504
    db_session.expire_all()
    status_response = client.get(f"/sessions/{session_id}/status")
    assert status_response.json()["pipeline_runs"][0]["status"] == "failed"
```

- [ ] **Step 4: Run the API tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api_sessions.py -v`
Expected: 32 passed (23 existing + 9 new, with the retargeted 501 test still counted among the 23).

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 253 passed, 2 skipped (244 + 9 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: wire cover_letter, recruiter_summary, interview_questions into run_stage"
```

---

### Task 8: ATS Report and Skill-Gap Report Endpoints

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_api_sessions.py`

**Interfaces:**
- Produces: `GET /sessions/{session_id}/reports/ats`, `GET /sessions/{session_id}/reports/skill-gap`. No new interfaces later tasks depend on.

- [ ] **Step 1: Add the two GET endpoints**

In `backend/app/api/sessions.py`, add this import near the top:

```python
from app.models.db_models import EvaluationRun, GapAnalysis
```

(If `EvaluationRun` or `GapAnalysis` is already imported from `app.models.db_models` on the existing import line, add these names to that existing line instead of a new import statement.)

Add these two routes, placed after the existing `list_documents` endpoint at the end of the file:

```python
@router.get("/{session_id}/reports/ats")
def get_ats_report(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    evaluation = (
        db.query(EvaluationRun)
        .filter_by(session_id=session_id)
        .order_by(EvaluationRun.id.desc())
        .first()
    )
    if evaluation is None:
        raise HTTPException(status_code=404, detail="evaluation has not succeeded for this session yet")

    raw = evaluation.raw_response_json or {}
    return {
        "session_id": session_id,
        "evaluation_run_id": evaluation.id,
        "overall_score": evaluation.overall_score,
        "open_source_score": evaluation.open_source_score,
        "projects_score": evaluation.projects_score,
        "production_score": evaluation.production_score,
        "technical_skills_score": evaluation.technical_skills_score,
        "rubric_version": evaluation.rubric_version,
        "hiring_agent_service_version": evaluation.hiring_agent_service_version,
        "evidence": raw.get("evidence"),
        "bonus_points": raw.get("bonus_points"),
        "deductions": raw.get("deductions"),
    }


@router.get("/{session_id}/reports/skill-gap")
def get_skill_gap_report(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    gap_analysis = (
        db.query(GapAnalysis)
        .filter_by(session_id=session_id)
        .order_by(GapAnalysis.id.desc())
        .first()
    )
    if gap_analysis is None:
        raise HTTPException(status_code=404, detail="gap_analysis has not succeeded for this session yet")

    analysis = gap_analysis.analysis_json or {}
    return {
        "session_id": session_id,
        "gap_analysis_id": gap_analysis.id,
        "matching_skills": analysis.get("matching_skills", []),
        "missing_skills": analysis.get("missing_skills", []),
        "experience_gap_notes": analysis.get("experience_gap_notes"),
        "relevant_projects": analysis.get("relevant_projects", []),
        "irrelevant_projects": analysis.get("irrelevant_projects", []),
        "recommended_keywords": analysis.get("recommended_keywords", []),
    }
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_api_sessions.py`:

```python
def test_get_ats_report_returns_404_when_evaluation_not_run(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/reports/ats")

    assert response.status_code == 404


def test_get_ats_report_reformats_latest_evaluation_run(client, db_session):
    from app.models.db_models import EvaluationRun

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    evaluation = EvaluationRun(
        session_id=session_id, resume_version_id=None,
        overall_score=88.0, open_source_score=30, projects_score=25,
        production_score=20, technical_skills_score=8,
        raw_response_json={
            "evidence": {"open_source": "3 popular repos"},
            "bonus_points": {"total": 5, "breakdown": "Active OSS contributor"},
            "deductions": {"total": 0, "reasons": "No deductions"},
        },
        rubric_version="hiring-agent-v1", hiring_agent_service_version="0.1.0",
    )
    db_session.add(evaluation)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/reports/ats")

    assert response.status_code == 200
    body = response.json()
    assert body["overall_score"] == 88.0
    assert body["evidence"] == {"open_source": "3 popular repos"}
    assert body["bonus_points"] == {"total": 5, "breakdown": "Active OSS contributor"}


def test_get_skill_gap_report_returns_404_when_gap_analysis_not_run(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/reports/skill-gap")

    assert response.status_code == 404


def test_get_skill_gap_report_reformats_latest_gap_analysis(client, db_session):
    from app.models.db_models import GapAnalysis

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    gap_analysis = GapAnalysis(
        session_id=session_id, resume_version_id=None, job_posting_id=job.id,
        analysis_json={
            "matching_skills": ["Python"], "missing_skills": ["Docker"],
            "experience_gap_notes": "JD wants 5+ years; resume shows 3.",
            "relevant_projects": ["Inventory Tracker"], "irrelevant_projects": [],
            "recommended_keywords": ["distributed systems"],
        },
    )
    db_session.add(gap_analysis)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/reports/skill-gap")

    assert response.status_code == 200
    body = response.json()
    assert body["matching_skills"] == ["Python"]
    assert body["missing_skills"] == ["Docker"]
    assert body["experience_gap_notes"] == "JD wants 5+ years; resume shows 3."
```

- [ ] **Step 3: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_api_sessions.py -v`
Expected: 36 passed (32 existing + 4 new).

- [ ] **Step 4: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 257 passed, 2 skipped (253 + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_api_sessions.py
git commit -m "feat: add ATS report and skill-gap report read endpoints"
```

---

### Task 9: `GET /{session_id}/documents` — Add `content` to the Response

**Files:**
- Modify: `backend/app/api/sessions.py`
- Create: `backend/tests/test_list_documents.py`

**Interfaces:** None new — this modifies an existing endpoint's response shape.

No test file for `GET /{session_id}/documents` exists anywhere in the current suite (confirmed by search — the endpoint has been untested since Phase 7). This task writes the first tests for it, covering both the pre-existing fields and this phase's `content` addition in one pass.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_list_documents.py`:

```python
from app.models.db_models import Resume, JobPosting, GeneratedDocument


def test_list_documents_returns_404_for_unknown_session(client):
    response = client.get("/sessions/999/documents")
    assert response.status_code == 404


def test_list_documents_returns_empty_list_when_none_generated(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/documents")

    assert response.status_code == 200
    assert response.json() == []


def test_list_documents_returns_null_content_for_pdf_type_document(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="resume_pdf",
        storage_path="/tmp/resume.pdf", content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["document_type"] == "resume_pdf"
    assert body[0]["storage_path"] == "/tmp/resume.pdf"
    assert body[0]["content"] is None
    assert body[0]["version_number"] == 1


def test_list_documents_returns_populated_content_for_text_type_document(client, db_session):
    """This phase's addition (spec §5): text-based document types (cover_letter,
    recruiter_summary, interview_questions) populate content and leave
    storage_path None - the reverse of the PDF row above. Before this task,
    content was never returned by this endpoint at all, making these three
    document types unreachable through the API despite being persisted."""
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="cover_letter",
        storage_path=None, content="Dear Hiring Manager, ...", version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["document_type"] == "cover_letter"
    assert body[0]["storage_path"] is None
    assert body[0]["content"] == "Dear Hiring Manager, ..."
```

- [ ] **Step 2: Run the tests to verify the content assertions fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_list_documents.py -v`
Expected: `test_list_documents_returns_null_content_for_pdf_type_document` and `test_list_documents_returns_populated_content_for_text_type_document` FAIL with `KeyError: 'content'` (the other two pass, since they don't touch `content`).

- [ ] **Step 3: Add `content` to the endpoint's response**

In `backend/app/api/sessions.py`, find the existing `list_documents` endpoint:

```python
@router.get("/{session_id}/documents")
def list_documents(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    documents = db.query(GeneratedDocument).filter_by(session_id=session_id).all()
    return [
        {"document_type": doc.document_type, "storage_path": doc.storage_path, "version_number": doc.version_number}
        for doc in documents
    ]
```

Replace the return statement's dict comprehension with:

```python
@router.get("/{session_id}/documents")
def list_documents(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    documents = db.query(GeneratedDocument).filter_by(session_id=session_id).all()
    return [
        {
            "document_type": doc.document_type,
            "storage_path": doc.storage_path,
            "content": doc.content,
            "version_number": doc.version_number,
        }
        for doc in documents
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_list_documents.py -v`
Expected: 4 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 261 passed, 2 skipped (257 + 4 new).

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_list_documents.py
git commit -m "fix: return content in GET /documents (previously unreachable for text-based document types)"
```

---

## Final Expected State

261 passed, 2 skipped (Postgres-gated migration test + Tectonic-gated compile test) in an environment without Tectonic — matching every prior phase's environmental-dependency-gating pattern. No new migration this phase (Task 3's spec confirmed `generated_documents.content` already exists from Phase 7).

At the final whole-branch review: no live-Docker/Tectonic verification is needed this phase (no LaTeX/PDF work), but do confirm a live Docker Compose `/health` check still passes, matching every phase's standard final-review baseline.
