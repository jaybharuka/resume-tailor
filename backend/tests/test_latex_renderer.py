from app.services.latex_renderer import LatexRenderer


def _fully_populated_resume() -> dict:
    return {
        "contact": {
            "full_name": "Jane Doe", "email": "jane@example.com", "phone": "555-1234",
            "location": "Springfield", "links": ["https://github.com/janedoe"],
        },
        "summary": "Backend engineer with 5 years of experience.",
        "work_experience": [
            {
                "company": "Acme Corp", "title": "Senior Backend Engineer",
                "start_date": "2021", "end_date": "2024",
                "bullets": ["Built payment systems"],
            },
        ],
        "projects": [
            {
                "name": "Task Queue", "description": "A distributed task queue",
                "bullets": ["400+ GitHub stars"], "technologies": ["Python", "Redis"],
            },
        ],
        "skills": ["Python", "PostgreSQL"],
        "education": [
            {
                "institution": "State University", "degree": "B.S.",
                "field_of_study": "Computer Science", "start_date": "2014", "end_date": "2018",
            },
        ],
        "certifications": ["AWS Certified Solutions Architect"],
    }


def test_latex_renderer_produces_valid_tex_for_fully_populated_resume():
    renderer = LatexRenderer(templates_root="latex_templates")

    tex_source = renderer.render(_fully_populated_resume())

    assert r"\documentclass" in tex_source
    assert r"\begin{document}" in tex_source
    assert r"\end{document}" in tex_source
    assert "Jane Doe" in tex_source
    assert "Springfield" in tex_source
    assert "Senior Backend Engineer" in tex_source
    assert "Task Queue" in tex_source
    assert "State University" in tex_source
    assert "AWS Certified Solutions Architect" in tex_source
    # No unresolved LaTeX-safe Jinja2 delimiters should remain in the output -
    # this would indicate a missing variable or a template typo.
    assert "<<" not in tex_source
    assert "%>" not in tex_source


def test_latex_renderer_handles_optional_fields_gracefully_for_sparse_resume():
    """Per this phase's spec: the first phase rendering the full breadth of
    ResumeDocument's optional fields into a document a real user sees, so
    missing/empty optional fields must degrade gracefully, not error or emit
    stray empty section headers."""
    sparse_resume = {
        "contact": {
            "full_name": "Alex Lee", "email": "alex@example.com", "phone": None,
            "location": None, "links": [],
        },
        "summary": None,
        "work_experience": [
            {
                "company": "Startup Co", "title": "Engineer",
                "start_date": "2022", "end_date": "2024", "bullets": [],
            },
        ],
        "projects": [],
        "skills": [],
        "education": [],
        "certifications": [],
    }

    tex_source = LatexRenderer(templates_root="latex_templates").render(sparse_resume)

    assert "Alex Lee" in tex_source
    assert "Startup Co" in tex_source
    assert r"\section*{Summary}" not in tex_source
    assert r"\section*{Projects}" not in tex_source
    assert r"\section*{Education}" not in tex_source
    assert r"\section*{Certifications}" not in tex_source
    assert "<<" not in tex_source
    assert "%>" not in tex_source


def test_latex_renderer_escapes_special_characters_in_resume_fields():
    resume = _fully_populated_resume()
    resume["work_experience"][0]["bullets"] = ["Improved throughput 40% using C++ & Python"]

    tex_source = LatexRenderer(templates_root="latex_templates").render(resume)

    assert r"40\%" in tex_source
    assert r"\&" in tex_source
    # The raw, unescaped characters must not appear in the rendered bullet text.
    assert "40% using" not in tex_source
    assert "C++ & Python" not in tex_source
