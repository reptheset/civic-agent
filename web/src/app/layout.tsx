import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Civic Agent",
  description: "Autonomous public-service execution agent",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="antialiased">{children}</body>
    </html>
  );
}
