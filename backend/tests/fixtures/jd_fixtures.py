"""Synthetic job-description text fixtures for tests. All company names,
titles, and content below are fabricated placeholders — not real job
postings, not scrubbed real listings."""


def complete_jd_text() -> str:
    return """Senior Backend Engineer at Acme Corp
Location: Remote (US)
Employment Type: Full-time

About the role:
We're looking for a Senior Backend Engineer to join our platform team.

Requirements:
- 5+ years of experience with Python or Go
- Experience with distributed systems and message queues
- Strong understanding of relational databases

Qualifications:
- Bachelor's degree in Computer Science or equivalent experience
- Experience mentoring junior engineers

Responsibilities:
- Design and implement backend services for our core platform
- Participate in on-call rotation
- Collaborate with product and design teams

Keywords: Python, Go, PostgreSQL, Kafka, distributed systems
"""


def no_requirements_header_jd_text() -> str:
    return """Marketing Coordinator at Widget LLC
Location: Chicago, IL

We're hiring a Marketing Coordinator. The ideal candidate has 2+ years of
experience in digital marketing, is comfortable with social media analytics
tools, and has excellent written communication skills. Responsibilities
include managing our social media calendar and coordinating with the design
team on campaign assets.
"""


def blurred_requirements_qualifications_jd_text() -> str:
    return """Data Analyst at Initech
Location: Austin, TX
Employment Type: Contract

Must-haves:
- Proficiency in SQL and Excel
- Experience with Tableau or similar BI tools
- 3+ years in a data analyst role

Responsibilities:
- Build and maintain dashboards for the sales team
- Perform ad-hoc data analysis requests
"""


def terse_jd_text() -> str:
    return "Barista at Corner Cafe. Part-time, in-person."


def not_a_job_posting_text() -> str:
    return """Dear team,

Just a reminder that the office will be closed next Monday for the holiday.
Please make sure to submit your timesheets before end of day Friday. Thanks
everyone for a great quarter!

Best,
Alex
"""
