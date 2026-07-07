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
