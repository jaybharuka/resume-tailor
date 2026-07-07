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
