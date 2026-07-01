import "../styles/globals.css";
import "@livekit/components-styles";
import "@livekit/components-styles/prefabs";
import type { Metadata, Viewport } from "next";
import { IBM_Plex_Mono, Inter, Space_Grotesk } from "next/font/google";
import { Toaster } from "react-hot-toast";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  weight: ["600"],
  variable: "--font-space-grotesk",
});

const ibmPlexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono",
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: {
    default: "Xaisen — Decentralized Video Network",
    template: "%s",
  },
  description:
    "Decentralized video conferencing on Sui. Workers provide compute, clients order rooms on-chain with escrow payments.",
  icons: {
    icon: {
      rel: "icon",
      url: "/favicon.ico",
    },
    apple: [
      {
        rel: "apple-touch-icon",
        url: "/images/livekit-apple-touch.png",
        sizes: "180x180",
      },
      {
        rel: "mask-icon",
        url: "/images/livekit-safari-pinned-tab.svg",
        color: "#080B10",
      },
    ],
  },
};

export const viewport: Viewport = {
  themeColor: "#080B10",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      className={`${spaceGrotesk.variable} ${ibmPlexMono.variable} ${inter.variable}`}
    >
      <body data-lk-theme="default">
        <Toaster />
        {children}
      </body>
    </html>
  );
}
