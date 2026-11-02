"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { ResQProvider, useResQ } from "../../context/ResQContext";
import { PortalRoleCategory, UserProfile, UserRole } from "../../types/resq";
import { DEMO_USERS } from "../../services/resqStorage";
import { StaffSignIn } from "./staff-sign-in";
import { backendLogin, checkBackendHealth } from "../../services/authApi";

// Administrator (Command & Dispatch) signs in against the backend; other tabs keep the demo flow.
const usesStaffSignIn = (category: PortalRoleCategory): boolean => category === "admin";

function LoginPageContent() {
  const router = useRouter();
  const { login, allUsers } = useResQ();
  // Protected workspace redirects arrive as /login?next=/dm...; open the staff tab for them.
  const next = useSearchParams().get("next") ?? undefined;

  const [selectedCategory, setSelectedCategory] = useState<PortalRoleCategory>(next?.startsWith("/dm") ? "admin" : "user");
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);
  const [backendConnected, setBackendConnected] = useState<boolean | null>(null);

  useEffect(() => {
    checkBackendHealth().then((isHealthy) => setBackendConnected(isHealthy));
  }, []);

  const handleCategoryChange = (cat: PortalRoleCategory) => {
    setSelectedCategory(cat);
    setErrorMsg(null);
  };

  const handleQuickDemoLogin = async (user: UserProfile) => {
    setErrorMsg(null);
    // SECURITY: Quick demo login is for citizens only. Privileged roles (admin, staff)
    // must authenticate via the real backend with MFA — never via a demo shortcut.
    const citizenRoles: UserRole[] = ["Public / Citizen"];
    if (!citizenRoles.includes(user.role)) {
      setErrorMsg("Privileged accounts cannot use Quick Demo login. Please use the Staff sign-in above.");
      return;
    }
    setSuccessMsg(`Signing in as ${user.name} (${user.role})...`);

    // Create demo token and establish session cookie for proxy routes (/report, /my-reports)
    try {
      const demoPayload = {
        sub: user.id || "citizen_demo",
        role: "NORMAL_USER",
        name: user.name,
        email: user.email,
      };
      const b64 = (obj: object) =>
        typeof window !== "undefined"
          ? btoa(unescape(encodeURIComponent(JSON.stringify(obj)))).replace(/=+$/, "")
          : Buffer.from(JSON.stringify(obj)).toString("base64url");
      const demoToken = `${b64({ alg: "HS256", typ: "JWT" })}.${b64(demoPayload)}.mock_signature`;

      await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: demoToken }),
      });
    } catch {
      // Continue even if session cookie endpoint failed
    }

    setTimeout(() => {
      login(user);
      if (next && next.startsWith("/") && !next.startsWith("//")) {
        router.push(next);
      } else {
        router.push("/");
      }
    }, 450);
  };

  const handleLoginSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    const identifier = loginEmail.trim().toLowerCase();
    const password = loginPassword.trim();

    if (!identifier) {
      setErrorMsg("Please enter your email or badge ID.");
      return;
    }

    // Find in local memory / storage
    const localMatch = allUsers.find(
      (u) =>
        u.email.toLowerCase() === identifier ||
        u.id.toLowerCase() === identifier ||
        (u.badgeNumber && u.badgeNumber.toLowerCase() === identifier)
    );

    // 1. Attempt Backend API Authentication (sharing profile info if recognized locally)
    const apiRes = await backendLogin(
      identifier,
      password,
      localMatch
        ? {
            role: localMatch.role,
            name: localMatch.name,
            agency: localMatch.agency,
          }
        : undefined
    );

    if (apiRes.success && apiRes.user) {
      if (apiRes.token) {
        await fetch("/api/session", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token: apiRes.token }),
        }).catch(() => {});
      }
      setSuccessMsg(`✓ Authenticated! Welcome back, ${apiRes.user.name}!`);
      setTimeout(() => {
        login(apiRes.user!);
        if (next && next.startsWith("/") && !next.startsWith("//")) {
          router.push(next);
        } else if (apiRes.user?.role === "Public / Citizen" || (apiRes.user?.role as unknown as string) === "NORMAL_USER") {
          router.push("/citizen/dashboard");
        } else {
          router.push("/");
        }
      }, 400);
      return;
    }

    // 2. Seamless Local Fallback (Only active when NEXT_PUBLIC_DEMO_MODE is true)
    if (process.env.NEXT_PUBLIC_DEMO_MODE === "true" && localMatch) {
      if (localMatch.password && password && localMatch.password !== password) {
        setErrorMsg("Incorrect password. Try using the 1-Click Quick Login below.");
        return;
      }
      setSuccessMsg(`Welcome back, ${localMatch.name}! Loading ${localMatch.role} dashboard...`);
      setTimeout(() => {
        login(localMatch);
        router.push(next || "/");
      }, 400);
      return;
    }

    // 3. Neither backend nor local matched
    setErrorMsg(
      apiRes.error || "Invalid credentials, or the account is temporarily unavailable."
    );
  };

  const demoPresets = DEMO_USERS.filter((u) => {
    if (selectedCategory === "user") return u.role === "Public / Citizen";
    if (selectedCategory === "admin") {
      return (
        u.role === "Command Officer / Incident Commander" ||
        u.role === "Dispatcher" ||
        u.role === "System Administrator"
      );
    }
    return (
      u.role === "Medic / Ambulance Team" ||
      u.role === "Firefighter / Fire Service Officer" ||
      u.role === "NDRF / SDRF Team Leader or Responder" ||
      u.role === "Logistics Officer"
    );
  });

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

        <div className="flex items-center gap-3">
          {backendConnected !== null && (
            <span
              className={`text-[10px] px-2.5 py-1 rounded-full font-medium border flex items-center gap-1.5 ${
                backendConnected
                  ? "bg-emerald-950/70 text-emerald-300 border-emerald-500/50"
                  : "bg-amber-950/70 text-amber-300 border-amber-500/50"
              }`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${backendConnected ? "bg-emerald-400" : "bg-amber-400"}`}></span>
              {backendConnected ? "FastAPI Online" : "Offline Demo"}
            </span>
          )}
          <Link
            href="/"
            className="text-xs bg-white/10 hover:bg-white/20 text-white px-3 py-1.5 rounded-full transition flex items-center gap-1.5"
          >
            <span>←</span> Return to General Dashboard
          </Link>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 flex items-center justify-center p-4 py-8">
        <div className="bg-[#0b1324] border border-slate-700/80 rounded-2xl shadow-2xl max-w-lg w-full p-6 md:p-8 space-y-6">
          <div className="text-center space-y-1">
            <h1 className="text-2xl font-extrabold text-white tracking-tight">
              Sign In to ResQ
            </h1>
            <p className="text-xs text-slate-400">
              Select your role category below to enter your operational workspace.
            </p>
          </div>

          {/* Role Category Selector */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-2">
              Who is logging in? <span className="text-sky-400">*</span>
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              <button
                type="button"
                onClick={() => handleCategoryChange("user")}
                className={`p-3 rounded-xl border text-left transition cursor-pointer flex flex-col justify-between ${
                  selectedCategory === "user"
                    ? "bg-sky-950/70 border-sky-500 shadow-md ring-1 ring-sky-500"
                    : "bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700"
                }`}
              >
                <span className="text-xl mb-1">👤</span>
                <div>
                  <div className={`text-xs font-bold ${selectedCategory === "user" ? "text-white" : "text-slate-300"}`}>
                    Citizen / User
                  </div>
                  <div className="text-[9.5px] text-slate-400">Distress SOS & Shelters</div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleCategoryChange("admin")}
                className={`p-3 rounded-xl border text-left transition cursor-pointer flex flex-col justify-between ${
                  selectedCategory === "admin"
                    ? "bg-blue-950/70 border-blue-500 shadow-md ring-1 ring-blue-500"
                    : "bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700"
                }`}
              >
                <span className="text-xl mb-1">🛡️</span>
                <div>
                  <div className={`text-xs font-bold ${selectedCategory === "admin" ? "text-white" : "text-slate-300"}`}>
                    Administrator
                  </div>
                  <div className="text-[9.5px] text-slate-400">Command & Dispatch</div>
                </div>
              </button>

              <button
                type="button"
                onClick={() => handleCategoryChange("service_provider")}
                className={`p-3 rounded-xl border text-left transition cursor-pointer flex flex-col justify-between ${
                  selectedCategory === "service_provider"
                    ? "bg-amber-950/70 border-amber-500 shadow-md ring-1 ring-amber-500"
                    : "bg-slate-900/60 border-slate-800 text-slate-400 hover:border-slate-700"
                }`}
              >
                <span className="text-xl mb-1">🚑</span>
                <div>
                  <div className={`text-xs font-bold ${selectedCategory === "service_provider" ? "text-white" : "text-slate-300"}`}>
                    Service Provider
                  </div>
                  <div className="text-[9.5px] text-slate-400">Medic, Fire & NDRF</div>
                </div>
              </button>
            </div>
          </div>

          {/* Quick 1-Click Demo (not offered for Administrator: staff use real authentication) */}
          {!usesStaffSignIn(selectedCategory) && (
          <div className="p-3 bg-slate-900/90 rounded-xl border border-slate-800">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] font-bold text-amber-400 flex items-center gap-1">
                <span>⚡</span> Quick 1-Click Test Presets:
              </span>
              <span className="text-[10px] text-slate-400">No typing needed</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {demoPresets.map((u) => (
                <button
                  key={u.id}
                  type="button"
                  onClick={() => handleQuickDemoLogin(u)}
                  className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 px-2.5 py-1.5 rounded-lg transition cursor-pointer flex items-center gap-1.5"
                >
                  <span className="font-semibold text-white">{u.name}</span>
                  <span className="text-[10px] text-sky-400 font-mono">({u.role.split("/")[0]})</span>
                </button>
              ))}
            </div>
          </div>
          )}

          {errorMsg && (
            <div className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2">
              <span>⚠️</span>
              <span>{errorMsg}</span>
            </div>
          )}
          {successMsg && (
            <div className="p-3 bg-emerald-950/80 border border-emerald-700/60 rounded-xl text-emerald-200 text-xs flex items-center gap-2">
              <span>✅</span>
              <span>{successMsg}</span>
            </div>
          )}

          {/* Form */}
          {usesStaffSignIn(selectedCategory) ? (
            <StaffSignIn next={next} />
          ) : (
          <form onSubmit={handleLoginSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-300 mb-1">
                Email Address or Badge ID
              </label>
              <input
                type="text"
                value={loginEmail}
                onChange={(e) => setLoginEmail(e.target.value)}
                placeholder={
                  selectedCategory === "user"
                    ? "citizen@example.com"
                    : selectedCategory === "admin"
                    ? "commander@resq.gov.in"
                    : "medic@resq.gov.in"
                }
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-xs font-semibold text-slate-300">Password</label>
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
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                placeholder="Enter password (e.g. admin123password)"
                className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
              />
            </div>

            <button
              type="submit"
              className="w-full bg-sky-600 hover:bg-sky-500 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 cursor-pointer flex items-center justify-center gap-2"
            >
              <span>Sign In as {selectedCategory === "user" ? "Citizen" : selectedCategory === "admin" ? "Administrator" : "Service Provider"}</span>
              <span>→</span>
            </button>
          </form>
          )}

          {/* Footer Navigation */}
          <div className="pt-3 border-t border-slate-800 text-center text-xs text-slate-400 space-y-2">
            <div>
              Don&apos;t have an account yet?{" "}
              <Link href="/signup" className="text-sky-400 hover:text-sky-300 font-bold underline">
                Sign Up / Register here
              </Link>
            </div>
            <div>
              <Link href="/" className="text-slate-400 hover:text-slate-200">
                Or continue browsing general dashboard as guest →
              </Link>
            </div>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="py-3 text-center text-[11px] text-slate-500 border-t border-slate-800/60 bg-slate-950">
        ResQ Disaster Response Coordination Hub • National Emergency Portal (112)
      </footer>
    </div>
  );
}

export default function LoginPage() {
  return (
    <ResQProvider>
      <Suspense fallback={null}>
        <LoginPageContent />
      </Suspense>
    </ResQProvider>
  );
}
