from tests.fixtures.gap_analysis_fixtures import (
    clean_missing_skills_pair, adjacent_not_matching_pair, synonym_matching_pair,
)


def test_clean_missing_skills_pair_has_no_overlap_between_resume_skills_and_jd_requirements():
    resume, job_posting = clean_missing_skills_pair()
    assert "Docker" not in resume.skills
    assert "Kubernetes" not in resume.skills
    assert "Docker" in job_posting.requirements
    assert "Kubernetes" in job_posting.requirements


def test_adjacent_not_matching_pair_has_different_frameworks_on_each_side():
    resume, job_posting = adjacent_not_matching_pair()
    assert "Django" in resume.skills
    assert "Flask" not in resume.skills
    assert "Flask" in job_posting.requirements


def test_synonym_matching_pair_has_genuine_abbreviation_relationship():
    resume, job_posting = synonym_matching_pair()
    assert "JavaScript" in resume.skills
    assert "JS" in job_posting.requirements
    assert "JS" not in resume.skills
