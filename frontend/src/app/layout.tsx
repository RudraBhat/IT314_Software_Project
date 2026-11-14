import type { Metadata } from "next";
import localFont from "next/font/local";
import "leaflet/dist/leaflet.css";
import "./globals.css";

const geistSans = localFont({
  src: "./fonts/GeistVF.woff2",
  variable: "--font-geist-sans",
  weight: "100 900",
});

const geistMono = localFont({
  src: "./fonts/GeistMonoVF.woff2",
  variable: "--font-geist-mono",
  weight: "100 900",
});

export const metadata: Metadata = {
  title: "ResQ | Emergency Disaster Response & Geo-Platform",
  description: "ResQ - Indian Disaster Response Coordination & Real-Time Emergency Mapping Hub",
  icons: { icon: "/icon.svg" },
};

export const viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} antialiased`}
    >
      <head>
        <link
          rel="stylesheet"
          href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        />
        <link
          rel="stylesheet"
          href="https://unpkg.com/leaflet-minimap@3.6.1/dist/Control.MiniMap.min.css"
        />
      </head>
      <body className="m-0 min-h-dvh w-full bg-slate-900 p-0 font-sans">
        {children}
      </body>
    </html>
  );
}
