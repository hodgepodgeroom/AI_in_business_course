import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Основа — заявки на закупку",
  description: "Подбор строительных материалов и составление закупочной заявки",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className="antialiased">{children}</body>
    </html>
  );
}
