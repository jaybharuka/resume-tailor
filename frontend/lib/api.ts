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
