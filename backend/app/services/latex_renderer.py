import jinja2

from app.services.latex_escape import escape_latex


class LatexRenderer:
    def __init__(self, templates_root: str):
        self.templates_root = templates_root
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(templates_root),
            variable_start_string="<<", variable_end_string=">>",
            block_start_string="<%", block_end_string="%>",
            comment_start_string="<#", comment_end_string="#>",
            trim_blocks=True, lstrip_blocks=True,
        )
        self._env.filters["latex_escape"] = escape_latex

    def render(self, resume_json: dict, template_name: str = "default") -> str:
        template = self._env.get_template(f"resume/{template_name}.tex")
        contact = resume_json.get("contact", {})
        contact_line_parts = [
            part for part in (contact.get("email"), contact.get("phone"), contact.get("location")) if part
        ]
        return template.render(resume=resume_json, contact_line_parts=contact_line_parts)
