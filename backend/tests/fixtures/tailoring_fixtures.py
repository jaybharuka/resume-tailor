"""Synthetic resume + JD + gap-analysis triples for tailoring-engine tests. All
names, companies, and content below are fabricated placeholders."""
from app.models.resume import ResumeDocument, ContactInfo, WorkExperience, Project
from app.models.job_posting import JobPostingDocument
from app.models.gap_analysis import GapAnalysisDocument


def base_tailoring_triple() -> tuple[ResumeDocument, JobPostingDocument, GapAnalysisDocument]:
    """A resume with two projects (used by the reorder-misattribution test to
    confirm identity-anchored change paths survive reordering), a JD requiring
    skills the resume doesn't have, and a matching gap analysis."""
    resume = ResumeDocument(
        contact=ContactInfo(full_name="Morgan Lee"),
        summary="Backend engineer.",
        work_experience=[
            WorkExperience(
                company="Acme Corp", title="Backend Engineer", start_date="2021", end_date="2024",
                bullets=["Worked on backend services"],
            ),
        ],
        projects=[
            Project(name="Inventory Tracker", bullets=["Built a tool to track inventory"], technologies=["Python"]),
            Project(name="Recipe Finder", bullets=["Built a recipe search tool"], technologies=["Python"]),
        ],
        skills=["Python", "Django", "PostgreSQL"],
    )
    job_posting = JobPostingDocument(
        title="Senior Backend Engineer",
        requirements=["Docker", "Kubernetes"],
    )
    gap_analysis = GapAnalysisDocument(
        matching_skills=["Python"],
        missing_skills=["Docker", "Kubernetes"],
        relevant_projects=["Inventory Tracker"],
        irrelevant_projects=["Recipe Finder"],
        recommended_keywords=["Docker", "distributed systems"],
    )
    return resume, job_posting, gap_analysis
