"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  acceptInvitation,
  verifyInvitationToken,
  verifyTotpSetup,
} from "../../services/authApi";

function SetupAccountContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") || "";

  // Verification state
  const [checkingToken, setCheckingToken] = useState(!!token);
  const [tokenValid, setTokenValid] = useState(false);
  const [tokenError, setTokenError] = useState<string | null>(
    token ? null : "Missing invitation token. Please open the link received in your invitation email.",
  );
  const [inviteInfo, setInviteInfo] = useState<{
    email?: string;
    full_name?: string;
    role?: string;
    requires_mfa?: boolean;
  }>({});

  // Step 1: Password setup
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [isSettingPassword, setIsSettingPassword] = useState(false);

  // Step 2: TOTP MFA enrollment (for privileged staff)
  const [step, setStep] = useState<"password" | "mfa" | "complete">("password");
  const [mfaData, setMfaData] = useState<{
    mfa_setup_token?: string;
    mfa_secret?: string;
    mfa_uri?: string;
  }>({});
  const [totpCode, setTotpCode] = useState("");
  const [isVerifyingTotp, setIsVerifyingTotp] = useState(false);
  const [copiedSecret, setCopiedSecret] = useState(false);

  // General feedback
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;

    verifyInvitationToken(token).then((res) => {
      setCheckingToken(false);
      setTokenValid(res.valid);
      if (res.valid) {
        setInviteInfo({
          email: res.email,
          full_name: res.full_name,
          role: res.role,
          requires_mfa: res.requires_mfa,
        });
      } else {
        setTokenError(res.error || "This invitation link is invalid or has expired.");
      }
    });
  }, [token]);

  // Step 1 Submit: Set Password
  const handlePasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (password.length < 12) {
      setErrorMsg("Password must be at least 12 characters long.");
      return;
    }
    if (password !== confirmPassword) {
      setErrorMsg("Passwords do not match.");
      return;
    }

    setIsSettingPassword(true);
    const res = await acceptInvitation(token, password);
    setIsSettingPassword(false);

    if (!res.success) {
      setErrorMsg(res.error || "Failed to accept invitation.");
      return;
    }

    if (res.mfa_required && res.mfa_setup_token) {
      setMfaData({
        mfa_setup_token: res.mfa_setup_token,
        mfa_secret: res.mfa_secret,
        mfa_uri: res.mfa_uri,
      });
      setStep("mfa");
    } else {
      setStep("complete");
      setSuccessMsg(res.message || "Account activated successfully!");
    }
  };

  // Step 2 Submit: Verify Initial TOTP
  const handleTotpSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!mfaData.mfa_setup_token) {
      setErrorMsg("Setup session expired. Please refresh the page.");
      return;
    }
    if (totpCode.trim().length !== 6) {
      setErrorMsg("Please enter a valid 6-digit verification code.");
      return;
    }

    setIsVerifyingTotp(true);
    const res = await verifyTotpSetup(mfaData.mfa_setup_token, totpCode);
    setIsVerifyingTotp(false);

    if (res.success && res.user) {
      setStep("complete");
      setSuccessMsg("Multi-factor authentication verified and account fully activated!");
      setTimeout(() => {
        router.push("/");
      }, 1500);
    } else {
      setErrorMsg(res.error || "Invalid 6-digit code. Check your authenticator app and try again.");
    }
  };

  const copySecret = () => {
    if (mfaData.mfa_secret) {
      navigator.clipboard.writeText(mfaData.mfa_secret);
      setCopiedSecret(true);
      setTimeout(() => setCopiedSecret(false), 2000);
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
        <div className="text-xs text-slate-400">
          Staff Account Setup
        </div>
      </header>

      <main className="flex-1 flex items-center justify-center p-4 py-12">
        <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl shadow-2xl max-w-lg w-full p-6 sm:p-8 space-y-6">
          {/* Header */}
          <div className="text-center space-y-2">
            <div className="w-12 h-12 rounded-xl bg-sky-500/20 border border-sky-400/40 flex items-center justify-center text-2xl mx-auto shadow-inner">
              {step === "mfa" ? "📲" : step === "complete" ? "✅" : "👋"}
            </div>
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              {step === "mfa"
                ? "Set Up Authenticator App"
                : step === "complete"
                ? "Setup Complete"
                : "Welcome to ResQ Hub"}
            </h1>
            <p className="text-xs text-slate-400 leading-relaxed">
              {step === "mfa"
                ? "Disaster management staff accounts require multi-factor authentication."
                : step === "complete"
                ? "Your credentials and security factors have been configured."
                : "Configure your credentials to activate your assigned operational account."}
            </p>
          </div>

          {/* Token verification loading */}
          {checkingToken ? (
            <div className="p-8 text-center space-y-3">
              <div className="w-8 h-8 border-2 border-sky-500 border-t-transparent rounded-full animate-spin mx-auto" />
              <p className="text-xs text-slate-400">Verifying invitation link…</p>
            </div>
          ) : !tokenValid ? (
            <div className="space-y-5 animate-fadeIn">
              <div className="p-4 bg-red-950/70 border border-red-700/60 rounded-xl text-xs text-red-200 flex items-start gap-3">
                <span className="text-base mt-0.5">⚠️</span>
                <div>
                  <p className="font-semibold">Invitation Link Invalid</p>
                  <p className="mt-1 text-slate-300">{tokenError}</p>
                </div>
              </div>
              <div className="pt-2 text-center">
                <Link
                  href="/login"
                  className="w-full inline-block bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-200 font-semibold py-2.5 px-4 rounded-xl text-xs transition"
                >
                  Return to Sign In
                </Link>
              </div>
            </div>
          ) : step === "complete" ? (
            <div className="space-y-5 animate-fadeIn text-center">
              <div className="p-4 bg-emerald-950/70 border border-emerald-600/60 rounded-xl text-xs text-emerald-200">
                <p className="font-semibold">{successMsg}</p>
                <p className="mt-1 text-slate-300">You can now access your assigned operational dashboard.</p>
              </div>
              <Link
                href="/login"
                className="w-full inline-block bg-sky-600 hover:bg-sky-500 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30"
              >
                Proceed to Operational Sign In →
              </Link>
            </div>
          ) : step === "mfa" ? (
            /* STEP 2: TOTP MFA Setup */
            <form onSubmit={handleTotpSubmit} className="space-y-4 animate-fadeIn">
              {errorMsg && (
                <div className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2 animate-shake">
                  <span>⚠️</span>
                  <span>{errorMsg}</span>
                </div>
              )}

              <div className="p-4 bg-slate-900 rounded-xl border border-slate-800 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-300">1. Authenticator Secret Key:</span>
                  <button
                    type="button"
                    onClick={copySecret}
                    className="text-[11px] text-sky-400 hover:text-sky-300 font-medium cursor-pointer"
                  >
                    {copiedSecret ? "✓ Copied!" : "Copy Key"}
                  </button>
                </div>
                <div className="p-2.5 bg-slate-950 border border-slate-800 rounded-lg text-center font-mono text-sm tracking-widest text-sky-300 select-all">
                  {mfaData.mfa_secret || "••••••••••••••••"}
                </div>
                <p className="text-[11px] text-slate-400 leading-normal">
                  Open <strong>Google Authenticator</strong>, <strong>Microsoft Authenticator</strong>, or any TOTP app, tap &quot;Add Account&quot; → &quot;Enter a setup key&quot;, and enter the key above.
                </p>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1.5">
                  2. Enter 6-Digit Code from App <span className="text-sky-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  maxLength={6}
                  value={totpCode}
                  onChange={(e) => setTotpCode(e.target.value.replace(/\D/g, ""))}
                  placeholder="e.g. 123456"
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-center font-mono text-lg tracking-widest text-white placeholder-slate-600 focus:outline-none focus:border-sky-500 transition"
                  autoFocus
                />
              </div>

              <button
                type="submit"
                disabled={isVerifyingTotp}
                className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 disabled:cursor-wait text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-emerald-600/30 flex items-center justify-center gap-2 cursor-pointer"
              >
                <span>{isVerifyingTotp ? "Verifying Authenticator…" : "Verify Code & Activate Account"}</span>
                <span>→</span>
              </button>
            </form>
          ) : (
            /* STEP 1: Set Password */
            <form onSubmit={handlePasswordSubmit} className="space-y-4">
              {/* Account summary banner */}
              <div className="p-3 bg-slate-900 rounded-xl border border-slate-800 flex items-center justify-between text-xs">
                <div>
                  <p className="font-bold text-white">{inviteInfo.full_name}</p>
                  <p className="text-[11px] text-slate-400 font-mono">{inviteInfo.email}</p>
                </div>
                <span className="text-[10px] font-semibold bg-sky-500/20 text-sky-300 border border-sky-500/30 px-2 py-0.5 rounded-full">
                  {inviteInfo.role}
                </span>
              </div>

              {errorMsg && (
                <div className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2 animate-shake">
                  <span>⚠️</span>
                  <span>{errorMsg}</span>
                </div>
              )}

              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="text-xs font-semibold text-slate-300">
                    Create Password <span className="text-sky-400">*</span>
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
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="Min 12 characters"
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Confirm Password <span className="text-sky-400">*</span>
                </label>
                <input
                  type={showPassword ? "text" : "password"}
                  required
                  minLength={12}
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Re-enter chosen password"
                  className="w-full bg-slate-900 border border-slate-700 rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition"
                />
              </div>

              {inviteInfo.requires_mfa && (
                <div className="p-3 bg-blue-950/40 rounded-lg border border-blue-900/60 text-[11px] text-blue-300 flex items-start gap-2">
                  <span>ℹ️</span>
                  <span>
                    Your assigned role (<strong>{inviteInfo.role}</strong>) requires multi-factor authentication. You will set up your authenticator app in the next step.
                  </span>
                </div>
              )}

              <button
                type="submit"
                disabled={isSettingPassword}
                className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-60 disabled:cursor-wait text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 flex items-center justify-center gap-2 cursor-pointer"
              >
                <span>
                  {isSettingPassword
                    ? "Saving Password…"
                    : inviteInfo.requires_mfa
                    ? "Continue to Authenticator Setup →"
                    : "Activate Account →"}
                </span>
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

export default function SetupAccountPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[#070d18] flex items-center justify-center text-slate-400">
          Loading…
        </div>
      }
    >
      <SetupAccountContent />
    </Suspense>
  );
}

