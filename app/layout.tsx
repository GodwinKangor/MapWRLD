import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dartmouth Energy Twin",
  description: "An interactive 3D digital twin for exploring Dartmouth College's campus and energy future.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
