import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "GitHub AI Engineer",
  description: "MCP-powered AI coding assistant for GitHub repositories",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
