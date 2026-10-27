import type { Metadata } from "next";
import { JetBrains_Mono } from "next/font/google";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const mono = JetBrains_Mono({ variable: "--font-mono-eva", subsets: ["latin"], weight: ["400", "500", "700"] });

export const metadata: Metadata = {
  title: "TONE ROOM",
  description: "로컬 영상 색·톤·필름 질감 보정 도구",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ko" className={`${mono.variable} h-full antialiased`}>
      <body className="min-h-full bg-black text-white">
        <TooltipProvider delay={300}>{children}</TooltipProvider>
      </body>
    </html>
  );
}
