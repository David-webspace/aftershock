import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "aftershock",
  description: "地震後的供應鏈應變：哪些供應商受影響、會不會斷料、怎麼補",
};

export const viewport: Viewport = {
  themeColor: "#0f1a24",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-Hant-TW" className="h-full antialiased">
      <body className="min-h-full">{children}</body>
    </html>
  );
}
