from pathlib import Path
import jinja2
from sqlalchemy.orm import Session
from app.models.db_models import PromptVersion


class PromptRegistry:
    def __init__(self, prompts_root: str):
        self.prompts_root = Path(prompts_root)
        self._env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(self.prompts_root)))

    def discover(self) -> list[tuple[str, str, str]]:
        """Return (task_type, version, template_path) for every template on disk."""
        found = []
        if not self.prompts_root.exists():
            return found
        for task_dir in sorted(self.prompts_root.iterdir()):
            if not task_dir.is_dir():
                continue
            for template_file in sorted(task_dir.glob("*.jinja2")):
                version = template_file.stem
                found.append((task_dir.name, version, str(template_file.relative_to(self.prompts_root))))
        return found

    def sync_to_db(self, db: Session) -> int:
        """Upsert a prompt_versions row for every template on disk. Returns rows created or updated."""
        touched = 0
        for task_type, version, template_path in self.discover():
            existing = (
                db.query(PromptVersion)
                .filter_by(task_type=task_type, version=version)
                .one_or_none()
            )
            if existing is None:
                db.add(PromptVersion(
                    task_type=task_type, name=task_type,
                    version=version, template_path=template_path,
                ))
                touched += 1
            elif existing.template_path != template_path:
                existing.template_path = template_path
                touched += 1
        db.commit()
        return touched

    def render(self, task_type: str, version: str, **context) -> str:
        template = self._env.get_template(f"{task_type}/{version}.jinja2")
        return template.render(**context)
