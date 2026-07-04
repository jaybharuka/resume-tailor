"""Synthetic resume/JD pairs for gap-analysis tests. All names, companies, and
content below are fabricated placeholders - not real resumes or job postings."""
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience
from app.models.job_posting import JobPostingDocument


def clean_missing_skills_pair() -> tuple[ResumeDocument, JobPostingDocument]:
    """Resume skilled in Python/Django/PostgreSQL vs. a JD requiring Docker/Kubernetes -
    a straightforward, unambiguous missing-skills case."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Jordan Kim"),
        work_experience=[
            WorkExperience(
                company="Startup Co", title="Backend Engineer", start_date="2021", end_date="2024",
                bullets=["Built REST APIs in Python and Django backed by PostgreSQL"],
            ),
        ],
        skills=["Python", "Django", "PostgreSQL"],
    )
    job_posting = JobPostingDocument(
        title="Platform Engineer",
        requirements=["Docker", "Kubernetes", "CI/CD pipeline experience"],
    )
    return resume, job_posting


def adjacent_not_matching_pair() -> tuple[ResumeDocument, JobPostingDocument]:
    """Resume with Django experience vs. a JD requiring Flask - two different Python web
    frameworks. Exercises the strict-match guard: Django must NOT be counted as
    satisfying the Flask requirement."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Sam Rivera"),
        work_experience=[
            WorkExperience(
                company="Widget LLC", title="Backend Developer", start_date="2020", end_date="2024",
                bullets=["Built and maintained Django web applications"],
            ),
        ],
        skills=["Python", "Django"],
    )
    job_posting = JobPostingDocument(
        title="Backend Developer",
        requirements=["Flask", "3+ years Python experience"],
    )
    return resume, job_posting


def synonym_matching_pair() -> tuple[ResumeDocument, JobPostingDocument]:
    """Resume lists 'JavaScript' vs. a JD requiring 'JS' - an unambiguous abbreviation.
    Exercises the reverse of the strict-match guard: the synonym must be correctly
    counted as a match, not treated as missing."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Alex Chen"),
        work_experience=[
            WorkExperience(
                company="Acme Corp", title="Frontend Engineer", start_date="2019", end_date="2024",
                bullets=["Built interactive UIs using JavaScript and React"],
            ),
        ],
        skills=["JavaScript", "React"],
    )
    job_posting = JobPostingDocument(
        title="Frontend Engineer",
        requirements=["JS", "React", "2+ years frontend experience"],
    )
    return resume, job_posting
