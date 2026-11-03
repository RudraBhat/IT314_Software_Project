"use client";

import React, { useActionState } from "react";
import Link from "next/link";
import { register } from "../login/actions";

export default function SignupPage() {
  const [state, formAction, isPending] = useActionState(register, {});

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
              Register as a citizen to access emergency SOS, incident reports, and public alerts.
            </p>
          </div>

          {/* Role notice */}
          <div className="flex items-start gap-3 p-3 bg-sky-950/50 border border-sky-800/60 rounded-xl text-sky-200 text-xs">
            <span className="text-base mt-0.5">ℹ️</span>
            <div>
              <span className="font-semibold">Public citizen accounts only.</span>{" "}
              Staff and responder accounts are issued by Application Management.
              If you are a responder or officer,{" "}
              <Link href="/login" className="underline text-sky-300 hover:text-sky-200">
                sign in here
              </Link>{" "}
              with your issued credentials.
            </div>
          </div>

          {/* Error Alert */}
          {state?.error && (
            <div
              role="alert"
              className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2"
            >
              <span>⚠️</span>
              <span>{state.error}</span>
            </div>
          )}

          {/* Form */}
          <form action={formAction} className="space-y-4">
            {/* Name + Phone */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label htmlFor="signup-name" className="block text-xs font-semibold text-slate-300 mb-1">
                  Full Name <span className="text-sky-400">*</span>
                </label>
                <input
                  id="signup-name"
                  name="full_name"
                  type="text"
                  required
                  placeholder="Ramesh Patel"
                  className={inputClass}
                  autoComplete="name"
                />
              </div>
              <div>
                <label htmlFor="signup-phone" className="block text-xs font-semibold text-slate-300 mb-1">
                  Phone Number
                </label>
                <input
                  id="signup-phone"
                  name="phone"
                  type="tel"
                  placeholder="+91 9876543210"
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
                name="email"
                type="email"
                required
                placeholder="citizen@example.in"
                className={inputClass}
                autoComplete="email"
              />
            </div>

            {/* Password */}
            <div>
              <label htmlFor="signup-password" className="block text-xs font-semibold text-slate-300 mb-1">
                Password <span className="text-sky-400">*</span>
              </label>
              <input
                id="signup-password"
                name="password"
                type="password"
                required
                placeholder="••••••••"
                className={inputClass}
                autoComplete="new-password"
              />
              <p className="text-[11px] text-slate-400 mt-1">
                Must be at least 8 characters with a digit and a symbol.
              </p>
            </div>

            <button
              type="submit"
              disabled={isPending}
              className="w-full bg-sky-600 hover:bg-sky-500 disabled:opacity-50 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-900/30 flex items-center justify-center gap-2 cursor-pointer"
            >
              {isPending ? (
                <>
                  <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Creating Account...
                </>
              ) : (
                "Create Citizen Account"
              )}
            </button>
          </form>

          {/* Footer Link */}
          <div className="text-center pt-2 border-t border-slate-800 text-xs text-slate-400">
            Already have an account?{" "}
            <Link href="/login" className="text-sky-400 hover:text-sky-300 font-semibold underline">
              Sign In
            </Link>
          </div>
        </div>
      </main>

      <footer className="text-center py-4 text-xs text-slate-500">
        ResQ · Disaster Response Coordination Hub · Government of Gujarat
      </footer>
    </div>
  );
}
