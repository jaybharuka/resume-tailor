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
