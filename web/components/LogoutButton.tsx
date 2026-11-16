"use client";

export function LogoutButton() {
  async function logout() {
    await fetch("/api/auth/logout", { method: "POST" });
    // 整頁載入：不留下上一位使用者在瀏覽器記憶體裡的資料
    window.location.replace("/login");
  }
  return <button onClick={logout} className="text-xs text-white/70 hover:text-white">登出</button>;
}
