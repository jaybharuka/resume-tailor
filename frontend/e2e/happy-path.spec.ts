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
    // Matches the backend's own STAGE_TIMEOUT_SECONDS (app/api/sessions.py) plus
    // margin for proxy/network overhead - a shorter client-side wait would fail
    // a stage that's genuinely still working server-side, not actually hung.
    await expect(row.getByText("Done")).toBeVisible({ timeout: 345_000 });
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
