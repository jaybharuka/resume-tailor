from fastapi import APIRouter, Depends
from pydantic import BaseModel, model_validator
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.models.db_models import JobPosting

router = APIRouter(prefix="/job-postings", tags=["job-postings"])


class CreateJobPostingRequest(BaseModel):
    source_url: str | None = None
    source_provider: str | None = None
    raw_text: str | None = None

    @model_validator(mode="after")
    def require_url_or_text(self):
        if not self.source_url and not self.raw_text:
            raise ValueError("either source_url or raw_text must be provided")
        return self


@router.post("", status_code=201)
def create_job_posting(request: CreateJobPostingRequest, db: Session = Depends(get_db)):
    posting = JobPosting(
        source_url=request.source_url,
        source_provider=request.source_provider,
        raw_text=request.raw_text,
    )
    db.add(posting)
    db.commit()
    db.refresh(posting)
    return {"id": posting.id, "source_url": posting.source_url}
