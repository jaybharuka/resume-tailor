"""Synthetic PDF resume fixtures for tests. All names, companies, and content
below are fabricated placeholders — not real people, not scrubbed real resumes."""
import pymupdf


def _build_pdf(lines: list[str]) -> bytes:
    doc = pymupdf.open()
    try:
        page = doc.new_page()
        y = 50
        for line in lines:
            page.insert_text((50, y), line, fontsize=11)
            y += 18
            if y > 780:
                page = doc.new_page()
                y = 50
        return doc.tobytes()
    finally:
        doc.close()


def build_normal_resume_pdf() -> bytes:
    return _build_pdf([
        "Jane Doe",
        "jane.doe@example.com | (555) 123-4567 | Springfield",
        "",
        "Summary",
        "Backend engineer with 5 years of experience building distributed systems.",
        "",
        "Experience",
        "Acme Corp - Senior Backend Engineer (2021-2024)",
        "- Designed and shipped a payments processing service handling 2M requests/day",
        "- Led migration from monolith to microservices, cutting deploy time by 60%",
        "",
        "Globex Inc - Backend Engineer (2018-2021)",
        "- Built internal analytics pipeline processing 500GB/day of event data",
        "",
        "Education",
        "State University - B.S. Computer Science (2014-2018)",
        "",
        "Projects",
        "Open Source Task Queue - a lightweight distributed task queue in Python",
        "- 400+ GitHub stars, used in production by three startups",
        "",
        "Skills",
        "Python, PostgreSQL, Docker, Kubernetes, AWS",
    ])


def build_no_summary_resume_pdf() -> bytes:
    return _build_pdf([
        "John Smith",
        "john.smith@example.com",
        "",
        "Experience",
        "Initech - Software Engineer (2020-2024)",
        "- Maintained a Django monolith serving 10k daily active users",
        "",
        "Education",
        "Tech Institute - B.S. Software Engineering (2016-2020)",
        "",
        "Skills",
        "Java, Spring, MySQL",
    ])


def build_sparse_bullets_resume_pdf() -> bytes:
    return _build_pdf([
        "Alex Lee",
        "alex.lee@example.com",
        "",
        "Experience",
        "Startup Co - Engineer (2022-2024)",
        "- Worked on backend",
        "",
        "Education",
        "Community College - A.S. Information Technology (2020-2022)",
    ])


def build_missing_section_resume_pdf() -> bytes:
    # Deliberately has no projects section at all.
    return _build_pdf([
        "Sam Rivera",
        "sam.rivera@example.com",
        "",
        "Summary",
        "Full-stack developer.",
        "",
        "Experience",
        "Widget LLC - Full-Stack Developer (2019-2024)",
        "- Built customer-facing dashboards using React and FastAPI",
        "",
        "Education",
        "Metro University - B.S. Information Systems (2015-2019)",
        "",
        "Skills",
        "JavaScript, React, FastAPI, PostgreSQL",
    ])


def build_many_pages_resume_pdf() -> bytes:
    """Forces the page-overflow branch in _build_pdf (y > 780) by exceeding ~40
    lines on a single page, so multi-page PDFs are actually exercised by a test."""
    lines = ["Alpha Marker"] + [f"Filler line {i}" for i in range(43)] + ["Omega Marker"]
    return _build_pdf(lines)


def build_blank_pdf() -> bytes:
    doc = pymupdf.open()
    try:
        doc.new_page()
        return doc.tobytes()
    finally:
        doc.close()
