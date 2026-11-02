"use client";

import React, { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { StaffSignIn } from "./staff-sign-in";

function LoginCard() {
  const searchParams = useSearchParams();
  const next = searchParams.get("next") ?? undefined;

  return (
    <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl shadow-2xl max-w-md w-full p-6 md:p-8 space-y-6">
      <div className="text-center space-y-1">
        <div className="w-14 h-14 rounded-full bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-3xl mx-auto mb-3">
          🔐
        </div>
        <h1 className="text-2xl font-extrabold text-white tracking-tight">
          Sign In
        </h1>
        <p className="text-xs text-slate-400">
          Disaster Management Staff, Responders, and Registered Citizens
        </p>
      </div>

      <StaffSignIn next={next} />

      <div className="text-center pt-2 border-t border-slate-800 text-xs text-slate-400 space-y-2">
        <div>
          Citizen without an account?{" "}
          <Link href="/signup" className="text-sky-400 hover:text-sky-300 font-semibold underline">
            Register here
          </Link>
        </div>
        <div>
          <Link href="/" className="text-slate-400 hover:text-slate-300">
            ← Return to Public Map
          </Link>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="min-h-screen w-screen bg-[#070d18] text-white flex flex-col justify-between overflow-x-hidden font-sans">
      <header className="h-14 bg-[#0c4a75] border-b border-[#093554] px-6 flex items-center justify-between shadow-md">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-sky-400/20 border border-white flex items-center justify-center text-lg">
            🛡️
          </div>
          <div>
            <div className="flex items-baseline gap-1.5 leading-tight">
              <span className="text-xl font-extrabold text-white">DRCH</span>
              <span className="text-xs font-light text-sky-200">GeoPlatform</span>
            </div>
            <div className="text-[9px] text-sky-200/80">NDMA Disaster Response Coordination Hub</div>
          </div>
        </Link>
      </header>

      <main className="flex-1 flex items-center justify-center p-4 py-8">
        <Suspense fallback={<div className="text-slate-400 text-sm">Loading sign-in...</div>}>
          <LoginCard />
        </Suspense>
      </main>

      <footer className="text-center py-4 text-xs text-slate-500">
        Disaster Response Coordination Hub (DRCH) · Government of Gujarat
      </footer>
    </div>
  );
}
