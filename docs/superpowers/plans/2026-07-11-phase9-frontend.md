# Phase 9: Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-flow Next.js UI that drives the full resume-tailoring pipeline — upload resume, paste job description, run all 9 backend stages in sequence, view/download every result — plus the one backend addition (a PDF download endpoint) the UI needs to actually retrieve a generated file.

**Architecture:** A brand-new `frontend/` Next.js (App Router) + TypeScript + Tailwind + shadcn/ui app talks to the existing FastAPI backend exclusively through a `next.config.js` rewrites proxy (`/api/*` → the backend), so no CORS middleware is added to the backend. One small, additive backend change (a new download route + an existing-endpoint fix) is built first since the frontend depends on it.

**Tech Stack:** Next.js 14+ (App Router), TypeScript, Tailwind CSS, shadcn/ui, Playwright (E2E only). Backend change is plain FastAPI/SQLAlchemy, matching the existing codebase.

## Global Constraints

- Node 20+ / npm (this environment has Node v22.16.0, npm 11.4.1 — confirmed working).
- `next.config.js` `rewrites()` proxies `/api/:path*` to the backend. No CORS middleware is added anywhere in this phase.
- The 9 pipeline stages, in the exact order `STAGE_RUNNERS` defines them in `backend/app/api/sessions.py`: `resume_parsing`, `jd_extraction`, `gap_analysis`, `tailoring_rewrite`, `evaluation`, `document_generation`, `cover_letter`, `recruiter_summary`, `interview_questions`.
- Every backend error is a FastAPI `HTTPException` with body `{"detail": "<message>"}` — the frontend's API client must extract `.detail` and surface it verbatim, never invent or reword it.
- Error UX split: a stage-run (`POST /run-stage/...`) failure renders in a labeled "Stage failed" block with the raw detail text verbatim (presentational only, no content translation). A report-read (`GET /reports/ats`, `GET /reports/skill-gap`) returning 404 because its prerequisite stage hasn't run yet renders a muted "Not generated yet" placeholder — never the error block, since this is a normal expected state, not a failure.
- `GET /sessions/{id}/documents` is missing its row `id` in the response today — this is a real, blocking gap (the frontend cannot build a per-document download URL without it) and gets fixed in Task 1 alongside the new download route.
- Windows test runner for the backend: `.venv\Scripts\python.exe -m pytest` (or `py -3 -m pytest`), run from `backend/`.
- Baseline backend suite before Task 1: 261 passed, 2 skipped.
- No component-level (React Testing Library) tests this phase — verification is one Playwright E2E test (Task 7) plus manual click-through. This is a deliberate, stated tradeoff (spec §8), not an oversight.
- **Worktree path quirk (discovered during Phase 8's final review, applies to every task in this plan that runs `docker compose up`):** `infra/docker-compose.yml`'s `hiring-agent-service` volume mount defaults to `${HIRING_AGENT_IMP_PATH:-../../hiring-agent-imp}`, a path meant to resolve correctly from the MAIN checkout's `infra/` directory. If this plan is executed inside a git worktree (e.g. `.worktrees/phase9-frontend/infra/`), that default resolves one level too shallow and points at a nonexistent directory. If `docker compose up` fails or `hiring-agent-service` can't find its sibling repo, set `HIRING_AGENT_IMP_PATH` explicitly to the absolute path of the real `hiring-agent-imp` checkout before running compose, e.g.: `HIRING_AGENT_IMP_PATH="c:/Reads/hiring-agent-imp/hiring-agent-imp" docker compose up -d --build` (adjust the absolute path to wherever that sibling repo actually lives in the current environment).

---

### Task 1: Backend — PDF Download Endpoint + `id` in `GET /documents`

**Files:**
- Modify: `backend/app/api/sessions.py`
- Modify: `backend/tests/test_list_documents.py`

**Interfaces:**
- Produces: `GET /sessions/{session_id}/documents/{document_id}/download` (streams PDF bytes, 404 on unknown session/document/missing file). `GET /sessions/{session_id}/documents` now includes `id` in each row's response dict. Later tasks (the frontend's `lib/api.ts`, Task 3) depend on both.

- [ ] **Step 1: Write the failing tests for the `id` field and the new download endpoint**

Add these imports and tests to `backend/tests/test_list_documents.py` (the file already imports `Resume, JobPosting, GeneratedDocument` from `app.models.db_models`; add these two more imports at the top):

```python
from app.core.storage import LocalDiskStorage
```

Add this assertion inside the existing `test_list_documents_returns_null_content_for_pdf_type_document` test, right after the existing `assert body[0]["version_number"] == 1` line:

```python
    assert body[0]["id"] == document.id
```

Add these new tests at the end of the file:

```python
def test_download_document_returns_pdf_bytes(client, db_session, tmp_path, monkeypatch):
    import app.api.sessions as sessions_module
    from app.core.config import Settings

    monkeypatch.setattr(sessions_module, "get_settings", lambda: Settings(storage_root=str(tmp_path)))

    storage = LocalDiskStorage(root=str(tmp_path))
    pdf_bytes = b"%PDF-1.4 fake pdf bytes"
    storage_path = storage.save("generated_documents/1/resume_pdf_v1.pdf", pdf_bytes)

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="resume_pdf",
        storage_path=storage_path, content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents/{document.id}/download")

    assert response.status_code == 200
    assert response.content == pdf_bytes
    assert response.headers["content-type"] == "application/pdf"
    assert "resume_pdf_v1.pdf" in response.headers["content-disposition"]


def test_download_document_returns_404_for_unknown_document(client, db_session):
    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    response = client.get(f"/sessions/{session_id}/documents/999/download")

    assert response.status_code == 404


def test_download_document_returns_404_when_document_belongs_to_different_session(client, db_session, tmp_path, monkeypatch):
    import app.api.sessions as sessions_module
    from app.core.config import Settings

    monkeypatch.setattr(sessions_module, "get_settings", lambda: Settings(storage_root=str(tmp_path)))
    storage = LocalDiskStorage(root=str(tmp_path))
    storage_path = storage.save("generated_documents/1/resume_pdf_v1.pdf", b"%PDF-1.4 fake pdf bytes")

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_a = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id}).json()["id"]
    session_b = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id}).json()["id"]

    document = GeneratedDocument(
        session_id=session_a, resume_version_id=None, document_type="resume_pdf",
        storage_path=storage_path, content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_b}/documents/{document.id}/download")

    assert response.status_code == 404


def test_download_document_returns_404_when_file_missing_from_storage(client, db_session, tmp_path, monkeypatch):
    import app.api.sessions as sessions_module
    from app.core.config import Settings

    monkeypatch.setattr(sessions_module, "get_settings", lambda: Settings(storage_root=str(tmp_path)))

    resume = Resume(original_filename="resume.pdf", storage_path="/tmp/resume.pdf")
    job = JobPosting(source_url="https://example.com/job")
    db_session.add_all([resume, job])
    db_session.commit()
    session_response = client.post("/sessions", json={"resume_id": resume.id, "job_posting_id": job.id})
    session_id = session_response.json()["id"]

    # storage_path points to a file that was never actually written to disk -
    # simulates the row surviving after the underlying file was moved/deleted.
    document = GeneratedDocument(
        session_id=session_id, resume_version_id=None, document_type="resume_pdf",
        storage_path=str(tmp_path / "generated_documents" / "1" / "resume_pdf_v1.pdf"),
        content=None, version_number=1,
    )
    db_session.add(document)
    db_session.commit()

    response = client.get(f"/sessions/{session_id}/documents/{document.id}/download")

    assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run (from `backend/`): `.venv\Scripts\python.exe -m pytest tests/test_list_documents.py -v`
Expected: FAIL — the `id` assertion fails with a `KeyError`-shaped assertion failure, and the 4 new download tests fail with 404 (route doesn't exist yet).

- [ ] **Step 3: Add `id` to `GET /documents`'s response**

In `backend/app/api/sessions.py`, find the existing `list_documents` endpoint:

```python
@router.get("/{session_id}/documents")
def list_documents(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    documents = db.query(GeneratedDocument).filter_by(session_id=session_id).all()
    return [
        {
            "document_type": doc.document_type,
            "storage_path": doc.storage_path,
            "content": doc.content,
            "version_number": doc.version_number,
        }
        for doc in documents
    ]
```

Replace the dict comprehension with one that also includes `id`:

```python
@router.get("/{session_id}/documents")
def list_documents(session_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")
    documents = db.query(GeneratedDocument).filter_by(session_id=session_id).all()
    return [
        {
            "id": doc.id,
            "document_type": doc.document_type,
            "storage_path": doc.storage_path,
            "content": doc.content,
            "version_number": doc.version_number,
        }
        for doc in documents
    ]
```

- [ ] **Step 4: Add the download endpoint**

In `backend/app/api/sessions.py`, add this import near the top (alongside the existing `from fastapi import ...` line — extend it):

```python
from fastapi import APIRouter, Depends, HTTPException, Response
```

Add this new route directly after `list_documents`:

```python
@router.get("/{session_id}/documents/{document_id}/download")
def download_document(session_id: int, document_id: int, db: Session = Depends(get_db)):
    session = db.get(TailoringSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id} not found")

    document = db.get(GeneratedDocument, document_id)
    if document is None or document.session_id != session_id:
        raise HTTPException(
            status_code=404, detail=f"document {document_id} not found for session {session_id}"
        )
    if document.storage_path is None:
        raise HTTPException(status_code=404, detail=f"document {document_id} has no downloadable file")

    settings = get_settings()
    storage = LocalDiskStorage(root=settings.storage_root)
    try:
        file_bytes = storage.load(document.storage_path)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail=f"file for document {document_id} is missing from storage"
        )

    filename = f"{document.document_type}_v{document.version_number}.pdf"
    return Response(
        content=file_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv\Scripts\python.exe -m pytest tests/test_list_documents.py -v`
Expected: 8 passed (4 existing + 4 new; the `id` assertion added to an existing test doesn't add a new test count, it's folded into an existing one).

- [ ] **Step 6: Run the full backend suite**

Run: `.venv\Scripts\python.exe -m pytest -q`
Expected: 265 passed, 2 skipped (261 baseline + 4 new tests).

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/sessions.py backend/tests/test_list_documents.py
git commit -m "feat: add PDF download endpoint and include document id in GET /documents"
```

---

### Task 2: Frontend Scaffold — Next.js + Tailwind + shadcn/ui + API Proxy

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/tsconfig.json`
- Create: `frontend/next.config.js`
- Create: `frontend/tailwind.config.ts`
- Create: `frontend/postcss.config.js`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/app/globals.css`
- Create: `frontend/app/page.tsx` (temporary placeholder — replaced by Task 4)
- Modify: `.gitignore` (repo root)

**Interfaces:**
- Produces: a working `npm run dev` Next.js app on port 3000, proxying `/api/*` to the backend on port 8020, with shadcn/ui's `Button`/`Card`/`Alert`/`Badge` components available at `@/components/ui/*` and the `cn()` helper at `@/lib/utils`. Tasks 3–7 build on this scaffold.

- [ ] **Step 1: Add frontend build artifacts to `.gitignore`**

Append to the repo root's `.gitignore`:

```
frontend/node_modules/
frontend/.next/
frontend/test-results/
frontend/playwright-report/
```

- [ ] **Step 2: Write the package manifest**

`frontend/package.json`:

```json
{
  "name": "resume-tailor-frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "next lint",
    "test:e2e": "playwright test"
  },
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "@types/node": "^20.12.0",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "@playwright/test": "^1.44.0"
  }
}
```

- [ ] **Step 3: Write the TypeScript config**

`frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2017",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": true,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Write the Next.js config with the API proxy**

`frontend/next.config.js`:

```javascript
/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8020";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
```

- [ ] **Step 5: Write the initial Tailwind + PostCSS config**

`frontend/tailwind.config.ts`:

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {},
  },
  plugins: [],
};

export default config;
```

`frontend/postcss.config.js`:

```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 6: Write the app shell**

`frontend/app/globals.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

`frontend/app/layout.tsx`:

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Resume Tailor",
  description: "AI resume tailoring pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
```

`frontend/app/page.tsx` (temporary — this gets fully replaced in Task 4 once the real upload flow exists; its only job right now is to prove the API proxy round-trips to the real backend):

```tsx
"use client";

import { useEffect, useState } from "react";

export default function Home() {
  const [health, setHealth] = useState<string>("loading...");

  useEffect(() => {
    fetch("/api/health")
      .then((res) => res.json())
      .then((data) => setHealth(JSON.stringify(data)))
      .catch((err) => setHealth(`error: ${err}`));
  }, []);

  return (
    <main className="p-6">
      <h1 className="text-2xl font-bold">Resume Tailor — scaffold check</h1>
      <p className="mt-2">Backend /api/health response: {health}</p>
    </main>
  );
}
```

- [ ] **Step 7: Install dependencies**

Run: `cd frontend && npm install`
Expected: completes with no errors, creates `frontend/node_modules/` and `frontend/package-lock.json`.

- [ ] **Step 8: Initialize shadcn/ui and add the components this phase needs**

Run (from `frontend/`): `npx shadcn@latest init --yes --defaults --base-color slate`

This detects the existing Next.js/Tailwind/TypeScript setup and creates `frontend/components.json`, `frontend/lib/utils.ts` (the `cn()` helper), and extends `frontend/tailwind.config.ts` and `frontend/app/globals.css` with shadcn's theme variables. **If this exact flag set is rejected** (the shadcn CLI updates its flags periodically since it's always fetched via `npx @latest`), run `npx shadcn@latest init --help` first to see the current flags, then re-run with whatever combination skips all interactive prompts and accepts the defaults — the goal is a fully non-interactive run that completes without a human answering prompts.

Then run: `npx shadcn@latest add button card alert badge --yes`

This generates `frontend/components/ui/button.tsx`, `card.tsx`, `alert.tsx`, and `badge.tsx` — all four are used by later tasks.

- [ ] **Step 9: Verify the dev server boots and the proxy reaches the real backend**

Start the backend (from `infra/`, if not already running): `docker compose up -d`

Then, from `frontend/`: `npm run dev`

Open `http://localhost:3100` in a browser (or `curl http://localhost:3100`) and confirm the page renders "Backend /api/health response:" followed by real JSON like `{"database":"ok","hiring_agent_service":"ok"}` — not an error, not "loading..." stuck forever. This proves the rewrites proxy genuinely reaches the Dockerized backend, not just that the frontend boots.

Stop the dev server (Ctrl+C) once confirmed.

- [ ] **Step 10: Commit**

```bash
git add .gitignore frontend/
git commit -m "feat: scaffold Next.js frontend with Tailwind, shadcn/ui, and API proxy"
```

---

### Task 3: Typed API Client

**Files:**
- Create: `frontend/lib/api.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure client-side code calling the proxy).
- Produces: `uploadResume`, `createJobPosting`, `createSession`, `runStage`, `getDocuments`, `downloadUrl`, `getAtsReport`, `getSkillGapReport`, `STAGE_NAMES`, `StageName`, `ApiError`, and the response type interfaces below. Tasks 4, 5, 6 import from this file exclusively — no task after this one calls `fetch` directly.

- [ ] **Step 1: Write the API client**

`frontend/lib/api.ts`:

```typescript
export interface UploadResumeResponse {
  id: number;
  original_filename: string;
  storage_path: string;
}

export interface CreateJobPostingResponse {
  id: number;
  source_url: string | null;
}

export interface CreateSessionResponse {
  id: number;
  status: string;
}

export interface RunStageResponse {
  stage_name: string;
  status: string;
  [key: string]: unknown;
}

export interface DocumentSummary {
  id: number;
  document_type: string;
  storage_path: string | null;
  content: string | null;
  version_number: number;
}

export interface AtsReport {
  session_id: number;
  evaluation_run_id: number;
  overall_score: number | null;
  open_source_score: number | null;
  projects_score: number | null;
  production_score: number | null;
  technical_skills_score: number | null;
  rubric_version: string | null;
  hiring_agent_service_version: string | null;
  evidence: unknown;
  bonus_points: unknown;
  deductions: unknown;
}

export interface SkillGapReport {
  session_id: number;
  gap_analysis_id: number;
  matching_skills: string[];
  missing_skills: string[];
  experience_gap_notes: string | null;
  relevant_projects: string[];
  irrelevant_projects: string[];
  recommended_keywords: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
    return JSON.stringify(body);
  } catch {
    return response.statusText || `request failed with status ${response.status}`;
  }
}

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init);
  if (!response.ok) {
    throw new ApiError(response.status, await parseErrorDetail(response));
  }
  return response.json() as Promise<T>;
}

export async function uploadResume(file: File): Promise<UploadResumeResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return requestJson<UploadResumeResponse>("/api/resumes", {
    method: "POST",
    body: formData,
  });
}

export async function createJobPosting(rawText: string): Promise<CreateJobPostingResponse> {
  return requestJson<CreateJobPostingResponse>("/api/job-postings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raw_text: rawText }),
  });
}

export async function createSession(
  resumeId: number,
  jobPostingId: number
): Promise<CreateSessionResponse> {
  return requestJson<CreateSessionResponse>("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_id: resumeId, job_posting_id: jobPostingId }),
  });
}

export async function runStage(sessionId: number, stageName: string): Promise<RunStageResponse> {
  return requestJson<RunStageResponse>(`/api/sessions/${sessionId}/run-stage/${stageName}`, {
    method: "POST",
  });
}

export async function getDocuments(sessionId: number): Promise<DocumentSummary[]> {
  return requestJson<DocumentSummary[]>(`/api/sessions/${sessionId}/documents`);
}

export function downloadUrl(sessionId: number, documentId: number): string {
  return `/api/sessions/${sessionId}/documents/${documentId}/download`;
}

export async function getAtsReport(sessionId: number): Promise<AtsReport | null> {
  const response = await fetch(`/api/sessions/${sessionId}/reports/ats`);
  if (response.status === 404) return null;
  if (!response.ok) throw new ApiError(response.status, await parseErrorDetail(response));
  return response.json() as Promise<AtsReport>;
}

export async function getSkillGapReport(sessionId: number): Promise<SkillGapReport | null> {
  const response = await fetch(`/api/sessions/${sessionId}/reports/skill-gap`);
  if (response.status === 404) return null;
  if (!response.ok) throw new ApiError(response.status, await parseErrorDetail(response));
  return response.json() as Promise<SkillGapReport>;
}

export const STAGE_NAMES = [
  "resume_parsing",
  "jd_extraction",
  "gap_analysis",
  "tailoring_rewrite",
  "evaluation",
  "document_generation",
  "cover_letter",
  "recruiter_summary",
  "interview_questions",
] as const;

export type StageName = (typeof STAGE_NAMES)[number];
```

- [ ] **Step 2: Verify it type-checks**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors. (There is no runtime test for this file in isolation — it has no logic branches beyond error-detail extraction, which gets exercised indirectly by Task 7's E2E test and by manual testing in Tasks 4–6.)

- [ ] **Step 3: Commit**

```bash
git add frontend/lib/api.ts
git commit -m "feat: add typed API client for the pipeline endpoints"
```

---

### Task 4: Upload + Job Posting + Create Session UI

**Files:**
- Create: `frontend/components/upload-form.tsx`
- Modify: `frontend/app/page.tsx` (replaces Task 2's temporary scaffold-check content)

**Interfaces:**
- Consumes: `uploadResume`, `createJobPosting`, `createSession`, `ApiError` from `@/lib/api` (Task 3); `Button`, `Card`, `CardContent`, `CardHeader`, `CardTitle` from `@/components/ui/*` (Task 2).
- Produces: `UploadForm` component with props `{ onSessionCreated: (sessionId: number) => void }`. Task 5 and Task 6's dispatchers into `page.tsx` (below) rely on `page.tsx` holding `sessionId` state, set here.

- [ ] **Step 1: Write the upload form component**

`frontend/components/upload-form.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createJobPosting, createSession, uploadResume, ApiError } from "@/lib/api";

interface UploadFormProps {
  onSessionCreated: (sessionId: number) => void;
}

export function UploadForm({ onSessionCreated }: UploadFormProps) {
  const [file, setFile] = useState<File | null>(null);
  const [jobText, setJobText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!file || !jobText.trim()) {
      setError("Please select a resume file and paste the job description text.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const resume = await uploadResume(file);
      const jobPosting = await createJobPosting(jobText);
      const session = await createSession(resume.id, jobPosting.id);
      onSessionCreated(session.id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Unexpected error");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>1. Upload Resume &amp; Job Posting</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div>
          <label className="mb-1 block text-sm font-medium" htmlFor="resume-file">
            Resume (PDF)
          </label>
          <input
            id="resume-file"
            type="file"
            accept="application/pdf"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            className="block w-full text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium" htmlFor="job-text">
            Job Description
          </label>
          <textarea
            id="job-text"
            value={jobText}
            onChange={(event) => setJobText(event.target.value)}
            rows={8}
            className="w-full rounded-md border p-2 text-sm"
            placeholder="Paste the job description text here..."
          />
        </div>
        {error && (
          <div className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-sm text-destructive">
            {error}
          </div>
        )}
        <Button onClick={handleSubmit} disabled={submitting}>
          {submitting ? "Creating session..." : "Start"}
        </Button>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Wire it into the page, replacing the scaffold-check content**

Replace the entire content of `frontend/app/page.tsx` with:

```tsx
"use client";

import { useState } from "react";
import { UploadForm } from "@/components/upload-form";

export default function Home() {
  const [sessionId, setSessionId] = useState<number | null>(null);

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-bold">Resume Tailor</h1>
      {sessionId === null ? (
        <UploadForm onSessionCreated={setSessionId} />
      ) : (
        <p className="text-sm text-muted-foreground">Session {sessionId} created. (Stage runner arrives in Task 5.)</p>
      )}
    </main>
  );
}
```

- [ ] **Step 3: Verify it type-checks**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manually verify against the real backend**

With the backend running (`docker compose up -d` from `infra/`) and `npm run dev` running from `frontend/`, open `http://localhost:3100`, select a real PDF file, paste any job description text, and click "Start". Confirm the page updates to show "Session N created." with a real numeric session id — not an error. If it errors, check the browser's network tab for which request failed and confirm the backend is actually reachable at `http://localhost:8020/health`.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/upload-form.tsx frontend/app/page.tsx
git commit -m "feat: add resume/job-posting upload form and session creation"
```

---

### Task 5: Stage Runner UI

**Files:**
- Create: `frontend/components/stage-runner.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `runStage`, `STAGE_NAMES`, `StageName`, `ApiError` from `@/lib/api` (Task 3); `Button`, `Card`, `CardContent`, `CardHeader`, `CardTitle`, `Badge` from `@/components/ui/*` (Task 2).
- Produces: `StageRunner` component with props `{ sessionId: number; onStageComplete: () => void }`. Task 6 relies on `page.tsx` calling `onStageComplete` to bump a `refreshKey` state value, passed to `ResultsPanel`.

- [ ] **Step 1: Write the stage runner component**

`frontend/components/stage-runner.tsx`:

```tsx
"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { runStage, STAGE_NAMES, ApiError, type StageName } from "@/lib/api";

type StageStatus = "idle" | "loading" | "done" | "failed";

const STAGE_LABELS: Record<StageName, string> = {
  resume_parsing: "Parse Resume",
  jd_extraction: "Extract Job Posting",
  gap_analysis: "Analyze Gaps",
  tailoring_rewrite: "Tailor Resume",
  evaluation: "Evaluate",
  document_generation: "Generate PDF",
  cover_letter: "Generate Cover Letter",
  recruiter_summary: "Generate Recruiter Summary",
  interview_questions: "Generate Interview Questions",
};

interface StageRunnerProps {
  sessionId: number;
  onStageComplete: () => void;
}

export function StageRunner({ sessionId, onStageComplete }: StageRunnerProps) {
  const [statuses, setStatuses] = useState<Record<StageName, StageStatus>>(
    () => Object.fromEntries(STAGE_NAMES.map((name) => [name, "idle"])) as Record<StageName, StageStatus>
  );
  const [errors, setErrors] = useState<Partial<Record<StageName, string>>>({});

  async function handleRunStage(stageName: StageName) {
    setStatuses((prev) => ({ ...prev, [stageName]: "loading" }));
    setErrors((prev) => ({ ...prev, [stageName]: undefined }));
    try {
      await runStage(sessionId, stageName);
      setStatuses((prev) => ({ ...prev, [stageName]: "done" }));
      onStageComplete();
    } catch (error) {
      const message = error instanceof ApiError ? error.message : "Unexpected error";
      setStatuses((prev) => ({ ...prev, [stageName]: "failed" }));
      setErrors((prev) => ({ ...prev, [stageName]: message }));
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>2. Pipeline Stages</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {STAGE_NAMES.map((stageName) => (
          <div
            key={stageName}
            data-testid={`stage-row-${stageName}`}
            className="flex flex-col gap-1 border-b pb-3 last:border-b-0"
          >
            <div className="flex items-center justify-between gap-3">
              <span className="font-medium">{STAGE_LABELS[stageName]}</span>
              <div className="flex items-center gap-2">
                <StageBadge status={statuses[stageName]} />
                <Button
                  size="sm"
                  variant={statuses[stageName] === "done" ? "outline" : "default"}
                  disabled={statuses[stageName] === "loading"}
                  onClick={() => handleRunStage(stageName)}
                >
                  {statuses[stageName] === "loading" ? "Running..." : "Run"}
                </Button>
              </div>
            </div>
            {statuses[stageName] === "failed" && errors[stageName] && (
              <div className="rounded-md border border-destructive/50 bg-destructive/10 p-2 text-sm text-destructive">
                <div className="font-semibold">Stage failed</div>
                <pre className="mt-1 whitespace-pre-wrap font-mono text-xs">{errors[stageName]}</pre>
              </div>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function StageBadge({ status }: { status: StageStatus }) {
  if (status === "idle") return <Badge variant="secondary">Not started</Badge>;
  if (status === "loading") return <Badge variant="secondary">Running</Badge>;
  if (status === "done") return <Badge variant="default">Done</Badge>;
  return <Badge variant="destructive">Failed</Badge>;
}
```

- [ ] **Step 2: Wire it into the page**

Replace the entire content of `frontend/app/page.tsx` with:

```tsx
"use client";

import { useState } from "react";
import { UploadForm } from "@/components/upload-form";
import { StageRunner } from "@/components/stage-runner";

export default function Home() {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-bold">Resume Tailor</h1>
      {sessionId === null ? (
        <UploadForm onSessionCreated={setSessionId} />
      ) : (
        <StageRunner sessionId={sessionId} onStageComplete={() => setRefreshKey((k) => k + 1)} />
      )}
    </main>
  );
}
```

(`refreshKey` isn't consumed by anything yet — Task 6 adds the `ResultsPanel` that reads it. It's introduced here because `StageRunner`'s `onStageComplete` callback needs somewhere to report to.)

- [ ] **Step 3: Verify it type-checks**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manually verify against the real backend**

With the backend and dev server running, go through Task 4's upload flow to create a session, then click "Run" on the first stage (`Parse Resume`). Confirm the badge changes Not started → Running → Done (or Failed with the error block, if you intentionally test a failure — e.g. click "Run" on "Tailor Resume" before running any earlier stage, and confirm the raw dependency-guard message appears in the error block).

- [ ] **Step 5: Commit**

```bash
git add frontend/components/stage-runner.tsx frontend/app/page.tsx
git commit -m "feat: add sequential stage runner UI"
```

---

### Task 6: Results Panel UI

**Files:**
- Create: `frontend/components/results-panel.tsx`
- Modify: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `getDocuments`, `getAtsReport`, `getSkillGapReport`, `downloadUrl`, `DocumentSummary`, `AtsReport`, `SkillGapReport` from `@/lib/api` (Task 3); `Card`, `CardContent`, `CardHeader`, `CardTitle` from `@/components/ui/*` (Task 2).
- Produces: `ResultsPanel` component with props `{ sessionId: number; refreshKey: number }`. Nothing later depends on this — it's the last UI piece before the E2E test.

- [ ] **Step 1: Write the results panel component**

`frontend/components/results-panel.tsx`:

```tsx
"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getAtsReport,
  getDocuments,
  getSkillGapReport,
  downloadUrl,
  type AtsReport,
  type DocumentSummary,
  type SkillGapReport,
} from "@/lib/api";

interface ResultsPanelProps {
  sessionId: number;
  refreshKey: number;
}

export function ResultsPanel({ sessionId, refreshKey }: ResultsPanelProps) {
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [atsReport, setAtsReport] = useState<AtsReport | null>(null);
  const [skillGapReport, setSkillGapReport] = useState<SkillGapReport | null>(null);

  useEffect(() => {
    getDocuments(sessionId).then(setDocuments);
    getAtsReport(sessionId).then(setAtsReport);
    getSkillGapReport(sessionId).then(setSkillGapReport);
  }, [sessionId, refreshKey]);

  const pdfDocuments = documents.filter((doc) => doc.document_type === "resume_pdf");
  const textDocuments = documents.filter((doc) => doc.document_type !== "resume_pdf");

  return (
    <Card>
      <CardHeader>
        <CardTitle>3. Results</CardTitle>
      </CardHeader>
      <CardContent className="space-y-6">
        <section>
          <h3 className="mb-2 font-semibold">Tailored Resume PDF</h3>
          {pdfDocuments.length === 0 ? (
            <p className="text-sm text-muted-foreground">Not generated yet.</p>
          ) : (
            <ul className="space-y-1">
              {pdfDocuments.map((doc) => (
                <li key={doc.id}>
                  <a
                    className="text-sm text-blue-600 underline"
                    href={downloadUrl(sessionId, doc.id)}
                    download
                  >
                    Download resume_pdf v{doc.version_number}
                  </a>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 font-semibold">Generated Text Documents</h3>
          {textDocuments.length === 0 ? (
            <p className="text-sm text-muted-foreground">Not generated yet.</p>
          ) : (
            <div className="space-y-3">
              {textDocuments.map((doc) => (
                <div key={doc.id} className="rounded-md border p-3">
                  <div className="mb-1 text-sm font-medium">
                    {doc.document_type} (v{doc.version_number})
                  </div>
                  <pre className="whitespace-pre-wrap text-sm">{doc.content}</pre>
                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h3 className="mb-2 font-semibold">ATS Report</h3>
          {atsReport === null ? (
            <p className="text-sm text-muted-foreground">Not generated yet.</p>
          ) : (
            <ul className="text-sm">
              <li>Overall score: {atsReport.overall_score ?? "—"}</li>
              <li>Open source score: {atsReport.open_source_score ?? "—"}</li>
              <li>Projects score: {atsReport.projects_score ?? "—"}</li>
              <li>Production score: {atsReport.production_score ?? "—"}</li>
              <li>Technical skills score: {atsReport.technical_skills_score ?? "—"}</li>
            </ul>
          )}
        </section>

        <section>
          <h3 className="mb-2 font-semibold">Skill Gap Report</h3>
          {skillGapReport === null ? (
            <p className="text-sm text-muted-foreground">Not generated yet.</p>
          ) : (
            <div className="space-y-1 text-sm">
              <p>Matching skills: {skillGapReport.matching_skills.join(", ") || "none"}</p>
              <p>Missing skills: {skillGapReport.missing_skills.join(", ") || "none"}</p>
              {skillGapReport.experience_gap_notes && <p>Notes: {skillGapReport.experience_gap_notes}</p>}
            </div>
          )}
        </section>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Wire it into the page**

Replace the entire content of `frontend/app/page.tsx` with:

```tsx
"use client";

import { useState } from "react";
import { UploadForm } from "@/components/upload-form";
import { StageRunner } from "@/components/stage-runner";
import { ResultsPanel } from "@/components/results-panel";

export default function Home() {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <main className="mx-auto max-w-3xl space-y-6 p-6">
      <h1 className="text-2xl font-bold">Resume Tailor</h1>
      {sessionId === null ? (
        <UploadForm onSessionCreated={setSessionId} />
      ) : (
        <>
          <StageRunner sessionId={sessionId} onStageComplete={() => setRefreshKey((k) => k + 1)} />
          <ResultsPanel sessionId={sessionId} refreshKey={refreshKey} />
        </>
      )}
    </main>
  );
}
```

- [ ] **Step 3: Verify it type-checks**

Run (from `frontend/`): `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Manually verify against the real backend**

Go through the full flow: upload → create session → run `resume_parsing` only, and confirm the results panel shows "Not generated yet." for the PDF, text documents, ATS report, and skill-gap report (since none of their prerequisite stages have run) — not an error block. Then run `gap_analysis` and confirm the Skill Gap Report section still correctly shows real data if `gap_analysis` succeeded, or stays "Not generated yet." if it hasn't run. This is the one behavior worth manually confirming carefully, since it's the exact ambiguity the spec's self-review caught (§6): a 404 for "not run yet" must never render as the stage-failure error block.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/results-panel.tsx frontend/app/page.tsx
git commit -m "feat: add results panel for documents and reports"
```

---

### Task 7: Playwright E2E Happy-Path Test

**Files:**
- Create: `frontend/playwright.config.ts`
- Create: `frontend/e2e/happy-path.spec.ts`
- Create: `frontend/e2e/fixtures/sample-resume.pdf` (binary fixture, generated by a one-off script, then committed)

**Interfaces:**
- Consumes: the full UI built in Tasks 4–6, and the real backend (Docker Compose) + real LLM providers. This is the final task — nothing depends on it.

**Important operational note before starting:** this test drives the real UI against the real Dockerized backend, which makes real NVIDIA/Gemini LLM API calls and a real Tectonic PDF compile — it needs `infra/.env`'s `GEMINI_API_KEY` (and `NVIDIA_API_KEY`) actually configured, exactly like every prior phase's manual smoke-test scripts have required. Because it exercises non-deterministic real LLM output through fabrication guards that CAN legitimately reject a bad model response, this test is not perfectly deterministic — an occasional real failure (not a flaky-test-infrastructure problem) is possible and should be re-run once before treating it as a genuine regression, the same way the project's other real-API smoke tests have always been understood.

- [ ] **Step 1: Generate the fixture resume PDF**

The backend already has a synthetic-resume PDF builder used by its own tests (`backend/tests/fixtures/pdf_fixtures.py`'s `build_normal_resume_pdf()`). Reuse it directly rather than writing new PDF-generation logic:

```bash
mkdir -p frontend/e2e/fixtures
cd backend && .venv/Scripts/python.exe -c "
import sys
sys.path.insert(0, 'tests')
from fixtures.pdf_fixtures import build_normal_resume_pdf
with open('../frontend/e2e/fixtures/sample-resume.pdf', 'wb') as f:
    f.write(build_normal_resume_pdf())
"
cd ..
```

Confirm the file was created and looks like a real PDF: `head -c 8 frontend/e2e/fixtures/sample-resume.pdf` should print `%PDF-1.` (or similar).

- [ ] **Step 2: Write the Playwright config**

`frontend/playwright.config.ts`:

```typescript
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 20 * 60 * 1000,
  use: {
    baseURL: "http://localhost:3100",
  },
});
```

The 20-minute per-test timeout accounts for 9 sequential real LLM-backed stage calls, each of which can legitimately take up to `STAGE_TIMEOUT_SECONDS` (330s) on the backend before it gives up — the test's own timeout must comfortably exceed the realistic total, not just one stage's worst case.

- [ ] **Step 3: Install Playwright's browser binaries**

Run (from `frontend/`): `npx playwright install --with-deps chromium`
Expected: downloads and installs a Chromium build for Playwright to drive. This requires network access, same as `npm install` did in Task 2.

- [ ] **Step 4: Write the E2E test**

`frontend/e2e/happy-path.spec.ts`:

```typescript
import { test, expect } from "@playwright/test";
import path from "path";

const STAGE_NAMES = [
  "resume_parsing",
  "jd_extraction",
  "gap_analysis",
  "tailoring_rewrite",
  "evaluation",
  "document_generation",
  "cover_letter",
  "recruiter_summary",
  "interview_questions",
];

test("full pipeline happy path: upload, run all stages, download PDF", async ({ page, request }) => {
  await page.goto("/");

  const fixturePath = path.join(__dirname, "fixtures", "sample-resume.pdf");
  await page.setInputFiles("#resume-file", fixturePath);
  await page.fill(
    "#job-text",
    [
      "Senior Backend Engineer at Acme Corp",
      "",
      "Requirements:",
      "- 5+ years of experience with Python",
      "- Experience with distributed systems",
      "- Strong understanding of relational databases",
    ].join("\n")
  );
  await page.getByRole("button", { name: "Start" }).click();

  for (const stageName of STAGE_NAMES) {
    const row = page.getByTestId(`stage-row-${stageName}`);
    await row.getByRole("button", { name: "Run" }).click();
    await expect(row.getByText("Done")).toBeVisible({ timeout: 120_000 });
  }

  const downloadLink = page.getByRole("link", { name: /Download resume_pdf/ });
  await expect(downloadLink).toBeVisible();
  const href = await downloadLink.getAttribute("href");
  expect(href).not.toBeNull();

  const response = await request.get(href!);
  expect(response.status()).toBe(200);
  const body = await response.body();
  expect(body.subarray(0, 5).toString()).toBe("%PDF-");
  expect(body.length).toBeGreaterThan(500);
});
```

- [ ] **Step 5: Run the test against the real stack**

Ensure the backend is running with real API keys configured: from `infra/`, `docker compose up -d --build` (confirm `infra/.env` has `GEMINI_API_KEY` and `NVIDIA_API_KEY` set first).

Start the frontend dev server in one terminal: `cd frontend && npm run dev`

In another terminal, run: `cd frontend && npx playwright test`

Expected: 1 passed. If a stage fails due to a real fabrication-guard rejection (a legitimate, if uncommon, real-model outcome) rather than a wiring bug, re-run once — per the operational note above, this is an accepted characteristic of exercising real, non-deterministic LLM providers end-to-end, not a bug in the test itself.

- [ ] **Step 6: Commit**

```bash
git add frontend/playwright.config.ts frontend/e2e/happy-path.spec.ts frontend/e2e/fixtures/sample-resume.pdf
git commit -m "test: add Playwright E2E test for the full pipeline happy path"
```

---

## Final Expected State

Backend: 265 passed, 2 skipped (261 baseline + 4 new tests from Task 1). Frontend: a working Next.js app at `frontend/`, one passing Playwright E2E test exercising the real backend end-to-end, `npx tsc --noEmit` clean across all TypeScript files.

At the final whole-branch review: confirm a live Docker Compose `/health` check passes (matching every phase's standard final-review baseline), and additionally confirm the Playwright E2E test itself passes against the live stack as the phase's core acceptance criterion — this phase's "real integration point nothing else tests for real" is the full browser-driven flow through all 9 stages, not a single endpoint.
