import type { Metadata } from "next";
import { Inter, Roboto_Mono } from "next/font/google";
import { Sidebar } from "@/components/layout/Sidebar";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import "./globals.css";

const inter = Inter({ 
  subsets: ["latin"],
  variable: '--font-inter',
});

const robotoMono = Roboto_Mono({
  subsets: ["latin"],
  variable: '--font-roboto-mono',
});

export const metadata: Metadata = {
  title: "Vision AI - Trading Terminal",
  description: "Institutional-Grade AI Quant Trading Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${robotoMono.variable} font-sans antialiased bg-slate-950 text-slate-50`}
      >
        <div className="flex h-screen overflow-hidden">
          <Sidebar />
          <div className="flex flex-1 flex-col min-w-0">
            <Navbar />
            <main className="flex-1 overflow-auto bg-[#0a0f1c]">
              <div className="flex flex-col min-h-max p-6 gap-6">
                <div className="flex-1">
                  {children}
                </div>
                <Footer />
              </div>
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
