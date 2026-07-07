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
