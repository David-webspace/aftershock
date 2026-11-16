// 前端呼叫後端的共用寫法：回傳錯誤訊息（成功時為 null）
export async function post(path: string, body?: unknown, method = "POST"): Promise<string | null> {
  const res = await fetch(path, {
    method, headers: body ? { "content-type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
  }).catch(() => null);
  if (!res) return "連不上伺服器";
  if (res.ok) return null;
  return ((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? "操作失敗";
}
