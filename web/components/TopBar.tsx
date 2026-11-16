import Link from "next/link";
import { apiGet } from "@/lib/api";
import type { Me } from "@/lib/types";
import { LogoutButton } from "./LogoutButton";

export async function TopBar() {
  const me = await apiGet<Me>("/api/me");
  return (
    <header className="border-b border-rule bg-ink text-white">
      <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2.5">
        <Link href={me.role === "sysadmin" ? "/admin" : "/"} className="font-cond text-2xl font-semibold tracking-tight">aftershock</Link>
        <span className="hidden text-xs text-white/60 sm:inline">Arcwell Electronics 供應鏈應變</span>
        <div className="ml-auto flex min-w-0 items-center gap-3 text-sm">
          <span className="truncate">{me.name}<span className="ml-1.5 text-white/60">{me.role_label}</span></span>
          <LogoutButton />
        </div>
      </div>
    </header>
  );
}
