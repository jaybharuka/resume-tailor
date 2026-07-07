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
