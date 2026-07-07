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
