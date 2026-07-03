from fastapi import FastAPI

app = FastAPI(title="Resume Tailor Backend")


@app.get("/")
def root():
    return {"service": "resume-tailor-backend"}
