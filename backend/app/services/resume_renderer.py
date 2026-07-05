def render_resume_to_text(resume_json: dict) -> str:
    """Render a structured resume (a resume_versions.resume_json value) into
    plain prose, since hiring-agent-service's /evaluate expects raw resume
    text (matching what ResumeEvaluator was built and tuned against), not
    structured JSON."""
    lines: list[str] = []

    contact = resume_json.get("contact", {})
    if contact.get("full_name"):
        lines.append(contact["full_name"])
    contact_line_parts = [
        part for part in (contact.get("email"), contact.get("phone"), contact.get("location")) if part
    ]
    if contact_line_parts:
        lines.append(" | ".join(contact_line_parts))
    for link in contact.get("links", []):
        lines.append(link)
    lines.append("")

    if resume_json.get("summary"):
        lines.append("Summary")
        lines.append(resume_json["summary"])
        lines.append("")

    work_experience = resume_json.get("work_experience", [])
    if work_experience:
        lines.append("Experience")
        for entry in work_experience:
            header = f"{entry.get('title', '')} at {entry.get('company', '')}"
            if entry.get("start_date") or entry.get("end_date"):
                header += f" ({entry.get('start_date', '')} - {entry.get('end_date', '')})"
            lines.append(header)
            for bullet in entry.get("bullets", []):
                lines.append(f"- {bullet}")
            lines.append("")

    projects = resume_json.get("projects", [])
    if projects:
        lines.append("Projects")
        for project in projects:
            lines.append(project.get("name", ""))
            if project.get("description"):
                lines.append(project["description"])
            for bullet in project.get("bullets", []):
                lines.append(f"- {bullet}")
            technologies = project.get("technologies", [])
            if technologies:
                lines.append(f"Technologies: {', '.join(technologies)}")
            lines.append("")

    skills = resume_json.get("skills", [])
    if skills:
        lines.append("Skills")
        lines.append(", ".join(skills))
        lines.append("")

    education = resume_json.get("education", [])
    if education:
        lines.append("Education")
        for entry in education:
            line = entry.get("institution", "")
            if entry.get("degree"):
                line += f" - {entry['degree']}"
            if entry.get("field_of_study"):
                line += f", {entry['field_of_study']}"
            if entry.get("start_date") or entry.get("end_date"):
                line += f" ({entry.get('start_date', '')} - {entry.get('end_date', '')})"
            lines.append(line)
        lines.append("")

    certifications = resume_json.get("certifications", [])
    if certifications:
        lines.append("Certifications")
        for cert in certifications:
            lines.append(f"- {cert}")
        lines.append("")

    return "\n".join(lines).strip()
