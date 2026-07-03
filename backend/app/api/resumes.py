import uuid
from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from app.api.deps import get_db
from app.core.storage import LocalDiskStorage
from app.core.config import get_settings
from app.models.db_models import Resume

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("", status_code=201)
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    settings = get_settings()
    storage = LocalDiskStorage(root=settings.storage_root)
    contents = await file.read()
    key = f"resumes/{uuid.uuid4()}/{file.filename}"
    storage_path = storage.save(key, contents)

    resume = Resume(original_filename=file.filename, storage_path=storage_path)
    db.add(resume)
    db.commit()
    db.refresh(resume)

    return {"id": resume.id, "original_filename": resume.original_filename, "storage_path": resume.storage_path}
