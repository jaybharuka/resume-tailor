from fastapi import FastAPI
from app.api import resumes, job_postings, sessions, health

app = FastAPI(title="Resume Tailor Backend")
app.include_router(resumes.router)
app.include_router(job_postings.router)
app.include_router(sessions.router)
app.include_router(health.router)


@app.get("/")
def root():
    return {"service": "resume-tailor-backend"}
