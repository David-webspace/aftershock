"use client";

import { useState } from "react";

// 示範帳號：讓評估者不用查文件就能切換角色（密碼見部署時的 SEED_DEMO_PASSWORD）
const DEMO = [
  { u: "scm.manager", who: "供應鏈主管", role: "全部料件，可選補救方案" },
  { u: "amy.chou", who: "採購", role: "半導體、連接器" },
  { u: "ben.lai", who: "採購", role: "被動元件、磁性元件" },
  { u: "cathy.wu", who: "採購", role: "PCB、機構件" },
  { u: "sysadmin", who: "系統管理員", role: "只看稽核紀錄" },
];

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ username, password }),
    }).catch(() => null);
    setBusy(false);
    if (!res) return setError("連不上伺服器，請確認服務已啟動");
    if (!res.ok) return setError(((await res.json().catch(() => ({}))) as { detail?: string }).detail ?? "登入失敗");
    const me = (await res.json()) as { role: string };
    // next 只接受站內路徑，否則登入頁會變成把人導去任意網站的跳板（//evil、/\evil 都會被瀏覽器當成外部網址）
    const next = new URLSearchParams(window.location.search).get("next");
    const safe = next && /^\/(?![/\\])/.test(next) ? next : null;
    window.location.replace(safe ?? (me.role === "sysadmin" ? "/admin" : "/"));
  }

  return (
    <main className="mx-auto grid min-h-dvh max-w-4xl items-center gap-10 px-4 py-10 md:grid-cols-[1fr_20rem]">
      <section className="min-w-0">
        <p className="font-cond text-6xl font-semibold tracking-tight">aftershock</p>
        <h1 className="mt-3 text-2xl break-words">地震後的供應鏈應變</h1>
        <p className="mt-4 max-w-md text-muted break-words">
          用真實地震的實際震度判斷哪些供應商受影響、哪些料件會斷料；詢問信要核准才寄出，回覆由模型整理、程式驗證，補救方案由求解器計算。
        </p>
        <div className="mt-8">
          <p className="mb-2 text-sm text-muted">示範帳號（點一下帶入）</p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {DEMO.map((d) => (
              <li key={d.u}>
                <button type="button" onClick={() => setUsername(d.u)}
                  className={`w-full rounded-sm border px-3 py-2 text-left hover:border-action ${username === d.u ? "border-action bg-action-wash" : "border-rule bg-sheet"}`}>
                  <span className="block font-medium">{d.who} <span className="num text-xs text-muted">{d.u}</span></span>
                  <span className="block text-xs text-muted">{d.role}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <form onSubmit={submit} className="rounded-sm border border-rule bg-sheet p-6">
        <h2 className="mb-4 text-xl font-medium">登入</h2>
        <label className="block text-sm text-muted" htmlFor="u">帳號</label>
        <input id="u" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required
          className="mt-1 mb-4 w-full rounded-sm border border-rule px-3 py-2 focus:border-action focus:outline-none" />
        <label className="block text-sm text-muted" htmlFor="p">密碼</label>
        <input id="p" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required
          className="mt-1 w-full rounded-sm border border-rule px-3 py-2 focus:border-action focus:outline-none" />
        <p className="mt-1.5 text-xs break-words text-muted">示範帳號密碼：專案資料夾 .env 的 SEED_DEMO_PASSWORD。</p>
        {error && <p role="alert" className="mt-3 text-sm text-stop">{error}</p>}
        <button disabled={busy} className="mt-6 w-full rounded-sm bg-action py-2.5 text-white hover:bg-action-deep disabled:opacity-50">
          {busy ? "登入中…" : "登入"}
        </button>
      </form>
    </main>
  );
}
