"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { submitResetPassword, verifyResetToken } from "../../services/authApi";

function ResetPasswordContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  const [checkingToken, setCheckingToken] = useState(true);
  const [tokenValid, setTokenValid] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(null);

  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setCheckingToken(false);
      setTokenValid(false);
      setTokenError("Missing password reset token. Please use the link sent to your email.");
      return;
    }

    verifyResetToken(token).then((res) => {
      setCheckingToken(false);
      setTokenValid(res.valid);
      if (!res.valid) {
        setTokenError(res.error || "This reset link is invalid or has expired.");
      }
    });
  }, [token]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (newPassword.length < 12) {
      setErrorMsg("New password must be at least 12 characters long.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setErrorMsg("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);
    const res = await submitResetPassword(token, newPassword);
    setIsSubmitting(false);

    if (res.success) {
      setSuccessMsg(res.message || "Your password has been reset successfully. Please log in.");
    } else {
      setErrorMsg(res.error || "Failed to reset password.");
    }
  };

  return (
    <div className="min-h-screen bg-[#070d18] text-slate-100 flex flex-col font-sans">
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

      <main className="flex-1 flex items-center justify-center p-4 py-12">
        <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl shadow-2xl max-w-md w-full p-6 sm:p-8 space-y-6">
          <div className="text-center space-y-2">
            <div className="w-12 h-12 rounded-xl bg-sky-500/20 border border-sky-400/40 flex items-center justify-center text-2xl mx-auto shadow-inner">
              🔒
            </div>
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              Create New Password
            </h1>
            <p className="text-xs text-slate-400 leading-relaxed">
              Choose a strong, unique password for your account.
            </p>
          </div>

          {checkingToken ? (
            <div className="p-6 text-center space-y-3">
              <div className="w-8 h-8 border-2 border-sky-500 border-t-transparent rounded-full animate-spin mx-auto" />
              <p className="text-xs text-slate-400">Verifying secure reset link…</p>
            </div>
          ) : !tokenValid ? (
            <div className="space-y-5 animate-fadeIn">
              <div className="p-4 bg-red-950/70 border border-red-700/60 rounded-xl text-xs text-red-200 flex items-start gap-3">
                <span className="text-base mt-0.5">⚠️</span>
                <div>
                  <p className="font-semibold">Reset Link Invalid</p>
                  <p className="mt-1 text-slate-300">{tokenError}</p>
                </div>
              </div>

              <div className="pt-2 text-center space-y-2">
                <Link
                  href="/forgot-password"
                  className="w-full inline-block bg-sky-600 hover:bg-sky-500 text-white font-bold py-2.5 px-4 rounded-xl text-xs transition shadow-lg shadow-sky-600/30 text-center"
                >
                  Request a New Reset Link
                </Link>
                <div>
                  <Link href="/login" className="text-xs text-slate-400 hover:text-slate-200 transition">
                    Return to Sign In
                  </Link>
                </div>
              </div>
            </div>
          ) : successMsg ? (
            <div className="space-y-5 animate-fadeIn">
              <div className="p-4 bg-emerald-950/70 border border-emerald-600/60 rounded-xl text-xs text-emerald-200 flex items-start gap-3">
                <span className="text-base mt-0.5">✅</span>
                <div>
                  <p className="font-semibold">Password Successfully Reset</p>
                  <p className="mt-1 text-slate-300">{successMsg}</p>
                </div>
              </div>

              <div className="pt-2">
                <Link
                  href="/login"
                  className="w-full inline-block bg-sky-600 hover:bg-sky-500 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 text-center"
                >
                  Sign In with New Password →
                </Link>
              </div>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {errorMsg && (
                <div className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2 animate-shake">
                  <span>⚠️</span>
                  <span>{errorMsg}</span>
                </div>
              )}

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-semibold text-slate-300">
                    New Password <span className="text-sky-400">*</span>
                  </label>
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    className="text-[11px] text-sky-400 hover:text-sky-300 cursor-pointer"
                  >
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={12}
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Min 12 characters"
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Confirm New Password <span className="text-sky-400">*</span>
                </label>
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={12}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter password"
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
                />
              </div>

              <div className="p-3 bg-slate-900/60 rounded-lg border border-slate-800 text-[11px] text-slate-400 space-y-1">
                <p className="font-medium text-slate-300">Password Security Requirements:</p>
                <ul className="list-disc pl-4 space-y-0.5 text-slate-400">
                  <li>At least 12 characters long</li>
                  <li>All active user sessions will be automatically revoked</li>
                  <li>Multi-factor authentication (if enabled) remains active</li>
                </ul>
              </div>

              <button
                type="submit"
                disabled={isSubmitting}
                className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-60 disabled:cursor-wait text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 flex items-center justify-center gap-2 cursor-pointer"
              >
                <span>{isSubmitting ? "Updating Password…" : "Set New Password"}</span>
                <span>→</span>
              </button>
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

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#070d18] flex items-center justify-center text-slate-400">
          Loading…
        </div>
      }
    >
      <ResetPasswordContent />
    </Suspense>
  );
}

