"use client";

import React, { useState } from "react";
import Link from "next/link";
import { requestPasswordReset } from "../../services/authApi";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [resultMessage, setResultMessage] = useState<string | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !email.includes("@")) return;

    setIsSubmitting(true);
    setResultMessage(null);

    const res = await requestPasswordReset(email);
    setIsSubmitting(false);
    setIsSuccess(res.success);
    setResultMessage(res.message);
  };

  return (
    <div className="min-h-screen bg-[#070d18] text-slate-100 flex flex-col font-sans">
      {/* Top Bar */}
      <header className="h-14 border-b border-slate-800 bg-[#0b1324]/90 backdrop-blur-md px-6 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="text-xl">🛡️</span>
          <span className="font-bold text-white text-base tracking-tight">
            ResQ <span className="font-light text-sky-400">Hub</span>
          </span>
        </Link>
        <Link
          href="/login"
          className="text-xs text-slate-400 hover:text-white transition flex items-center gap-1"
        >
          <span>←</span> Back to Sign In
        </Link>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex items-center justify-center p-4 py-12">
        <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl shadow-2xl max-w-md w-full p-6 sm:p-8 space-y-6">
          <div className="text-center space-y-2">
            <div className="w-12 h-12 rounded-xl bg-sky-500/20 border border-sky-400/40 flex items-center justify-center text-2xl mx-auto shadow-inner">
              🔑
            </div>
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              Forgot Password
            </h1>
            <p className="text-xs text-slate-400 leading-relaxed">
              Enter your registered email address and we&apos;ll send you a secure link to reset your password.
            </p>
          </div>

          {resultMessage ? (
            <div className="space-y-5 animate-fadeIn">
              <div
                className={`p-4 rounded-xl border text-xs leading-relaxed flex items-start gap-3 ${
                  isSuccess
                    ? "bg-emerald-950/70 border-emerald-600/60 text-emerald-200"
                    : "bg-red-950/70 border-red-600/60 text-red-200"
                }`}
              >
                <span className="text-base mt-0.5">{isSuccess ? "📬" : "⚠️"}</span>
                <div>
                  <p className="font-semibold">{isSuccess ? "Reset Link Dispatched" : "Unable to Process"}</p>
                  <p className="mt-1 text-slate-300">{resultMessage}</p>
                </div>
              </div>

              <div className="text-center space-y-2 pt-2 border-t border-slate-800">
                <Link
                  href="/login"
                  className="w-full inline-block bg-sky-600 hover:bg-sky-500 text-white font-bold py-2.5 px-4 rounded-xl text-xs transition shadow-lg shadow-sky-600/30 text-center"
                >
                  Return to Sign In
                </Link>
                <button
                  type="button"
                  onClick={() => {
                    setResultMessage(null);
                    setEmail("");
                  }}
                  className="text-xs text-slate-400 hover:text-slate-200 transition underline underline-offset-2"
                >
                  Try another email
                </button>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  Registered Email Address <span className="text-sky-400">*</span>
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="name@domain.gov.in"
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
                  autoFocus
                />
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-60 disabled:cursor-wait text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 flex items-center justify-center gap-2 cursor-pointer"
              >
                <span>{isSubmitting ? "Sending Reset Link…" : "Send Reset Link"}</span>
                <span>→</span>
              </button>

              <div className="pt-2 text-center text-xs text-slate-400">
                Remember your password?{" "}
                <Link href="/login" className="text-sky-400 hover:text-sky-300 font-semibold underline">
                  Sign In
                </Link>
              </div>
            </form>
          )}
        </div>
      </main>

      <footer className="py-3 text-center text-[11px] text-slate-500 border-t border-slate-800/60 bg-slate-950">
        ResQ Disaster Response Coordination Hub • National Emergency Portal (112)
      </footer>
    </div>
  );
}

