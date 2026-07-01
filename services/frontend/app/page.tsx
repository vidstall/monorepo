"use client";

import dynamic from "next/dynamic";

const HomePage = dynamic(() => import("./HomePage"), { ssr: false });

export default function Page() {
  return <HomePage />;
}
