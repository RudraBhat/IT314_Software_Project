"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ResQProvider, useResQ } from "../../context/ResQContext";
import { backendSignup } from "../../services/authApi";

/**
 * Public self-registration — Citizens / general public ONLY.
 *
 * Security rule: This form always produces a "Public / Citizen" account.
 * Administrator and Service Provider accounts are provisioned exclusively by
 * Application Management via the backend CLI (app.cli) and require MFA.
 * No client-supplied role is ever trusted.
 */
function SignupPageContent() {
  const router = useRouter();
  const { signup } = useResQ();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("+91 ");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSignupSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!fullName.trim()) {
      setErrorMsg("Please enter your full name.");
      return;
    }
    if (!email.trim() || !email.includes("@")) {
      setErrorMsg("Please enter a valid email address.");
      return;
    }
    if (!phone.trim() || phone.trim() === "+91") {
      setErrorMsg("Please enter your phone number.");
      return;
    }
    if (password.length < 8) {
      setErrorMsg("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setErrorMsg("Passwords do not match.");
      return;
    }

    setIsSubmitting(true);

    try {
      const res = await backendSignup({
        name: fullName.trim(),
        email: email.trim().toLowerCase(),
        phone: phone.trim(),
        role: "Public / Citizen",
        agency: "Public Resident / Citizen",
        password: password,
      });

      if (!res.success && !res.isOffline) {
        setErrorMsg(res.error || "Registration failed. Please try again.");
        setIsSubmitting(false);
        return;
      }

      if (res.isOffline) {
        if (process.env.NEXT_PUBLIC_DEMO_MODE === "true") {
          signup({
            name: fullName.trim(),
            email: email.trim().toLowerCase(),
            phone: phone.trim(),
            role: "Public / Citizen",
            agency: "Public Resident / Citizen",
            password: password,
          });
        } else {
          setErrorMsg("Registration service is temporarily unreachable. Please try again shortly.");
          setIsSubmitting(false);
          return;
        }
      }

      setSuccessMsg(`Welcome, ${fullName.trim()}! Your citizen account has been created. Redirecting to login...`);
      setTimeout(() => {
        router.push("/login");
      }, 1200);
    } catch {
      setErrorMsg("An unexpected error occurred during registration. Please try again.");
      setIsSubmitting(false);
    }
  };

  const inputClass =
    "w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500 transition";

  return (
    <div className="min-h-screen w-screen bg-[#070d18] text-white flex flex-col justify-between overflow-x-hidden font-sans">
      {/* Top Banner */}
      <header className="h-14 bg-[#0c4a75] border-b border-[#093554] px-6 flex items-center justify-between shadow-md">
        <Link href="/" className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-sky-400/20 border border-white flex items-center justify-center text-lg">
            🛡️
          </div>
          <div>
            <div className="flex items-baseline gap-1.5 leading-tight">
              <span className="text-xl font-extrabold text-white">ResQ</span>
              <span className="text-xs font-light text-sky-200">GeoPlatform</span>
            </div>
            <div className="text-[9px] text-sky-200/80">NDMA Disaster Response Coordination Hub</div>
          </div>
        </Link>

        <Link
          href="/"
          className="text-xs bg-white/10 hover:bg-white/20 text-white px-3 py-1.5 rounded-full transition flex items-center gap-1.5"
        >
          <span>←</span> Return to Dashboard
        </Link>
      </header>

      <main className="flex-1 flex items-center justify-center p-4 py-8">
        <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl shadow-2xl max-w-md w-full p-6 md:p-8 space-y-6">

          {/* Header */}
          <div className="text-center space-y-1">
            <div className="w-14 h-14 rounded-full bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-3xl mx-auto mb-3">
              👤
            </div>
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              Citizen Registration
            </h1>
            <p className="text-xs text-slate-400">
              Register as a citizen to access emergency SOS, shelter maps, and public alerts.
            </p>
          </div>

          {/* Role notice */}
          <div className="flex items-start gap-3 p-3 bg-sky-950/50 border border-sky-800/60 rounded-xl text-sky-200 text-xs">
            <span className="text-base mt-0.5">ℹ️</span>
            <div>
              <span className="font-semibold">Public citizen accounts only.</span>
              {" "}Staff and administrator accounts are issued by Application Management.
              If you are a responder or officer,{" "}
              <Link href="/login" className="underline text-sky-300 hover:text-sky-200">
                sign in here
              </Link>{" "}with your issued credentials.
            </div>
          </div>

          {/* Error / Success */}
          {errorMsg && (
            <div role="alert" className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2">
              <span>⚠️</span>
              <span>{errorMsg}</span>
            </div>
          )}
          {successMsg && (
            <div role="status" className="p-3 bg-emerald-950/80 border border-emerald-700/60 rounded-xl text-emerald-200 text-xs flex items-center gap-2">
              <span>✅</span>
              <span>{successMsg}</span>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSignupSubmit} className="space-y-4">
            {/* Name + Phone */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="signup-name" className="block text-xs font-semibold text-slate-300 mb-1">
                  Full Name <span className="text-sky-400">*</span>
                </label>
                <input
                  id="signup-name"
                  type="text"
                  required
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="e.g. Ramesh Chandra"
                  className={inputClass}
                  autoComplete="name"
                />
              </div>
              <div>
                <label htmlFor="signup-phone" className="block text-xs font-semibold text-slate-300 mb-1">
                  Phone Number <span className="text-sky-400">*</span>
                </label>
                <input
                  id="signup-phone"
                  type="tel"
                  required
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+91 98765 43210"
                  className={inputClass}
                  autoComplete="tel"
                />
              </div>
            </div>

            {/* Email */}
            <div>
              <label htmlFor="signup-email" className="block text-xs font-semibold text-slate-300 mb-1">
                Email Address <span className="text-sky-400">*</span>
              </label>
              <input
                id="signup-email"
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className={inputClass}
                autoComplete="email"
              />
            </div>

            {/* Password */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor="signup-password" className="text-xs font-semibold text-slate-300">
                  Password <span className="text-sky-400">*</span>
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
                id="signup-password"
                type={showPassword ? "text" : "password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 8 characters"
                className={inputClass}
                autoComplete="new-password"
              />
            </div>

            {/* Confirm Password */}
            <div>
              <label htmlFor="signup-confirm" className="block text-xs font-semibold text-slate-300 mb-1">
                Confirm Password <span className="text-sky-400">*</span>
              </label>
              <input
                id="signup-confirm"
                type={showPassword ? "text" : "password"}
                required
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter password"
                className={inputClass}
                autoComplete="new-password"
              />
            </div>

            <div className="pt-1">
              <button
                id="signup-submit"
                type="submit"
                disabled={isSubmitting}
                className="w-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-60 disabled:cursor-wait text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-emerald-600/30 cursor-pointer flex items-center justify-center gap-2"
              >
                <span>{isSubmitting ? "Creating account…" : "Create Citizen Account"}</span>
                <span>→</span>
              </button>
            </div>
          </form>

          {/* Footer nav */}
          <div className="pt-3 border-t border-slate-800 text-center text-xs text-slate-400 space-y-2">
            <div>
              Already have an account?{" "}
              <Link href="/login" className="text-sky-400 hover:text-sky-300 font-bold underline">
                Sign In here
              </Link>
            </div>
            <div>
              <Link href="/" className="text-slate-400 hover:text-slate-200">
                Browse as guest →
              </Link>
            </div>
          </div>
        </div>
      </main>

      <footer className="py-3 text-center text-[11px] text-slate-500 border-t border-slate-800/60 bg-slate-950">
        ResQ Disaster Response Coordination Hub • National Emergency Portal (112)
      </footer>
    </div>
  );
}

export default function SignupPage() {
  return (
    <ResQProvider>
      <SignupPageContent />
    </ResQProvider>
  );
}
