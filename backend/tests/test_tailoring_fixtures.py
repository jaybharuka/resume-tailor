from tests.fixtures.tailoring_fixtures import base_tailoring_triple


def test_base_tailoring_triple_has_two_projects_for_reorder_testing():
    resume, job_posting, gap_analysis = base_tailoring_triple()
    assert [project.name for project in resume.projects] == ["Inventory Tracker", "Recipe Finder"]


def test_base_tailoring_triple_gap_analysis_names_a_missing_skill_not_in_resume():
    resume, job_posting, gap_analysis = base_tailoring_triple()
    assert "Docker" in gap_analysis.missing_skills
    assert "Docker" not in resume.skills


def test_base_tailoring_triple_has_no_flask_anywhere_in_resume_or_matching_skills():
    """Flask must be genuinely absent from the original resume (skills, bullets,
    and every project's technologies) and from gap_analysis.matching_skills, so
    Task 6's unearned-adjacent-skill guard test has a clean vector to add Flask
    to and assert it gets rejected as unearned."""
    resume, job_posting, gap_analysis = base_tailoring_triple()
    assert "Flask" not in resume.skills
    assert "Flask" not in gap_analysis.matching_skills
    for project in resume.projects:
        assert "Flask" not in project.technologies
        assert all("Flask" not in bullet for bullet in project.bullets)
    for entry in resume.work_experience:
        assert all("Flask" not in bullet for bullet in entry.bullets)
