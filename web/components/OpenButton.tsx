"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function OpenButton({ scenario, label = "開應變案" }: { scenario: string; label?: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function open() {
    setBusy(true);
    setError(null);
    const res = await fetch("/api/incidents", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ scenario }),
    }).catch(() => null);
    const body = res ? ((await res.json().catch(() => ({}))) as { id?: number; detail?: string }) : {};
    if (!res?.ok || !body.id) {
      setBusy(false);
      return setError(body.detail ?? "開案失敗，請稍後再試");
    }
    router.push(`/incidents/${body.id}`);
  }

  return (
    <div>
      <button onClick={open} disabled={busy}
        className="rounded-sm bg-action px-3 py-1.5 text-sm text-white hover:bg-action-deep disabled:opacity-50">
        {busy ? "計算影響中…" : label}
      </button>
      {error && <p role="alert" className="mt-1 text-xs break-words text-stop">{error}</p>}
    </div>
  );
}
