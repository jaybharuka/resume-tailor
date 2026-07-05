from app.services.resume_renderer import render_resume_to_text


def test_render_resume_to_text_includes_all_populated_sections():
    resume_json = {
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

    text = render_resume_to_text(resume_json)

    assert "Jane Doe" in text
    assert "jane@example.com" in text
    assert "https://github.com/janedoe" in text
    assert "Backend engineer with 5 years of experience." in text
    assert "Senior Backend Engineer" in text
    assert "Acme Corp" in text
    assert "Built payment systems" in text
    assert "Task Queue" in text
    assert "A distributed task queue" in text
    assert "400+ GitHub stars" in text
    assert "Python, Redis" in text
    assert "Python, PostgreSQL" in text
    assert "State University" in text
    assert "B.S." in text
    assert "Computer Science" in text
    assert "AWS Certified Solutions Architect" in text


def test_render_resume_to_text_omits_empty_sections_for_sparse_resume():
    resume_json = {
        "contact": {"full_name": "Alex Lee", "email": None, "phone": None, "location": None, "links": []},
        "summary": None,
        "work_experience": [
            {
                "company": "Startup Co", "title": "Engineer",
                "start_date": "2022", "end_date": "2024", "bullets": ["Worked on backend"],
            },
        ],
        "projects": [],
        "skills": [],
        "education": [],
        "certifications": [],
    }

    text = render_resume_to_text(resume_json)

    assert "Alex Lee" in text
    assert "Startup Co" in text
    assert "Summary" not in text
    assert "Projects" not in text
    assert "Skills" not in text
    assert "Education" not in text
    assert "Certifications" not in text
