"use client";

import React, { useState } from "react";
import { useResQ } from "../context/ResQContext";
import { PortalRoleCategory, UserProfile, UserRole } from "../types/resq";
import { DEMO_USERS } from "../services/resqStorage";
import { StaffSignIn } from "../app/login/staff-sign-in";
import { backendLogin, backendSignup } from "../services/authApi";
import { GoogleSignInButton } from "./GoogleSignInButton";

interface AuthModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialMode?: "login" | "signup";
  initialRoleCategory?: PortalRoleCategory;
}

export const AuthModal: React.FC<AuthModalProps> = ({
  isOpen,
  onClose,
  initialMode = "login",
  initialRoleCategory = "user",
}) => {
  const { login, signup, allUsers } = useResQ();

  const [mode, setMode] = useState<"login" | "signup">(initialMode);
  const [selectedCategory, setSelectedCategory] = useState<PortalRoleCategory>(initialRoleCategory);
  const [showPassword, setShowPassword] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Login form state
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");

  // Signup form state
  const [fullName, setFullName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupPhone, setSignupPhone] = useState("+91 ");
  const [specificRole, setSpecificRole] = useState<UserRole>("Public / Citizen");
  const [agency, setAgency] = useState("");
  const [badgeNumber, setBadgeNumber] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");

  if (!isOpen) return null;

  // Handle switching category
  const handleCategoryChange = (cat: PortalRoleCategory) => {
    setSelectedCategory(cat);
    setErrorMsg(null);
    if (cat === "user") {
      setSpecificRole("Public / Citizen");
      setAgency("Public Resident / Citizen");
    } else if (cat === "admin") {
      setSpecificRole("Command Officer / Incident Commander");
      setAgency("National Disaster Management Authority (NDMA)");
    } else {
      setSpecificRole("Medic / Ambulance Team");
      setAgency("Emergency Medical Services (EMS 108)");
    }
  };

  // Quick One-Click Demo Login
  const handleQuickDemoLogin = async (user: UserProfile) => {
    setErrorMsg(null);
    setSuccessMsg(`Signing in as ${user.name} (${user.role})...`);
    // Attempt backend sync in background
    backendLogin(user.email, user.password || "").catch(() => {});
    setTimeout(() => {
      login(user);
      setSuccessMsg(null);
      onClose();
    }, 450);
  };

  // Submit Login
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
      setSuccessMsg(`✓ Authenticated via FastAPI Gateway! Welcome back, ${apiRes.user.name}!`);
      setTimeout(() => {
        login(apiRes.user!);
        setSuccessMsg(null);
        onClose();
      }, 400);
      return;
    }

    // 2. Seamless Local Fallback (Guarantees zero downtime if backend is offline or syncing)
    if (localMatch) {
      if (localMatch.password && password && localMatch.password !== password) {
        setErrorMsg("Incorrect password. Try using the 1-Click Quick Login below.");
        return;
      }
      setSuccessMsg(`Welcome back, ${localMatch.name}! Loading ${localMatch.role} dashboard...`);
      setTimeout(() => {
        login(localMatch);
        setSuccessMsg(null);
        onClose();
      }, 400);
      return;
    }

    // 3. Neither backend nor local matched
    setErrorMsg(
      apiRes.error ||
        `No account found matching "${identifier}". You can use the Quick Demo buttons below or Sign Up.`
    );
  };

  // Submit Signup
  const handleSignupSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg(null);

    if (!fullName.trim()) {
      setErrorMsg("Please enter your full name.");
      return;
    }
    if (!signupEmail.trim() || !signupEmail.includes("@")) {
      setErrorMsg("Please enter a valid email address.");
      return;
    }
    if (signupPassword.length < 6) {
      setErrorMsg("Password must be at least 6 characters.");
      return;
    }
    if (signupPassword !== confirmPassword) {
      setErrorMsg("Passwords do not match.");
      return;
    }

    // Determine role based on category
    let finalRole: UserRole = specificRole;
    if (selectedCategory === "user") {
      finalRole = "Public / Citizen";
    }

    // Attempt backend sync in background
    backendSignup({
      name: fullName.trim(),
      email: signupEmail.trim(),
      phone: signupPhone.trim(),
      role: finalRole,
      agency: agency.trim() || (selectedCategory === "user" ? "Public Resident" : "Emergency Operations Division"),
      badgeNumber: badgeNumber.trim() || undefined,
      password: signupPassword,
    }).catch(() => {});

    const newUser = signup({
      name: fullName.trim(),
      email: signupEmail.trim(),
      phone: signupPhone.trim(),
      role: finalRole,
      agency: agency.trim() || (selectedCategory === "user" ? "Public Resident" : "Emergency Operations Division"),
      badgeNumber: badgeNumber.trim() || undefined,
      password: signupPassword,
    });

    setSuccessMsg(`Account created for ${newUser.name}! Entering your customized dashboard...`);
    setTimeout(() => {
      setSuccessMsg(null);
      onClose();
    }, 500);
  };

  // Filter demo presets for the selected role category
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
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/75 backdrop-blur-md p-4 animate-fadeIn">
      <div className="bg-[#0b1222] border border-slate-700/80 text-white rounded-2xl shadow-2xl max-w-xl w-full flex flex-col overflow-hidden max-h-[92vh]">
        {/* Header Bar */}
        <div className="p-4 px-6 bg-gradient-to-r from-sky-950 via-[#0c4a75] to-slate-900 border-b border-sky-800/40 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-sky-500/20 border border-sky-400/40 flex items-center justify-center text-xl shadow-inner">
              🛡️
            </div>
            <div>
              <h2 className="text-base font-bold tracking-tight text-white flex items-center gap-2">
                ResQ Portal Authentication
                <span className="text-[10px] uppercase font-semibold bg-sky-500/20 text-sky-300 border border-sky-500/30 px-2 py-0.5 rounded-full">
                  Multi-Role Access
                </span>
              </h2>
              <p className="text-xs text-sky-200/80">
                Disaster Response Coordination Hub • Select your operational role
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white hover:bg-white/10 w-8 h-8 rounded-full flex items-center justify-center transition cursor-pointer text-base"
            title="Close / Continue to General Dashboard"
          >
            ✕
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-5">
          {/* Sign In vs Sign Up Tabs */}
          <div className="flex bg-slate-900/90 p-1 rounded-xl border border-slate-800">
            <button
              type="button"
              onClick={() => {
                setMode("login");
                setErrorMsg(null);
              }}
              className={`flex-1 py-2 text-xs font-bold rounded-lg transition cursor-pointer flex items-center justify-center gap-2 ${
                mode === "login"
                  ? "bg-sky-600 text-white shadow-md shadow-sky-600/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>🔐</span> Sign In
            </button>
            <button
              type="button"
              onClick={() => {
                setMode("signup");
                setErrorMsg(null);
              }}
              className={`flex-1 py-2 text-xs font-bold rounded-lg transition cursor-pointer flex items-center justify-center gap-2 ${
                mode === "signup"
                  ? "bg-sky-600 text-white shadow-md shadow-sky-600/30"
                  : "text-slate-400 hover:text-slate-200"
              }`}
            >
              <span>📝</span> Create Account / Sign Up
            </button>
          </div>

          {/* QUESTION: "Who is logging in?" */}
          <div>
            <label className="block text-xs font-bold uppercase tracking-wider text-slate-300 mb-2">
              Step 1: Who is logging in? <span className="text-sky-400">*</span>
            </label>
            <div className="grid grid-cols-3 gap-2.5">
              {/* Option 1: User / Citizen */}
              <button
                type="button"
                onClick={() => handleCategoryChange("user")}
                className={`p-3 rounded-xl border text-left transition cursor-pointer flex flex-col justify-between ${
                  selectedCategory === "user"
                    ? "bg-sky-950/70 border-sky-500 shadow-md shadow-sky-500/20 ring-1 ring-sky-500"
                    : "bg-slate-900/60 border-slate-800 hover:border-slate-700 text-slate-400"
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xl">👤</span>
                  {selectedCategory === "user" && (
                    <span className="w-2 h-2 rounded-full bg-sky-400 shadow-[0_0_8px_#38bdf8]" />
                  )}
                </div>
                <div>
                  <div className={`text-xs font-bold ${selectedCategory === "user" ? "text-white" : "text-slate-300"}`}>
                    Citizen / User
                  </div>
                  <div className="text-[10px] text-slate-400 leading-tight mt-0.5">
                    Report SOS, track reports & safe shelters
                  </div>
                </div>
              </button>

              {/* Option 2: Administrator */}
              <button
                type="button"
                onClick={() => handleCategoryChange("admin")}
                className={`p-3 rounded-xl border text-left transition cursor-pointer flex flex-col justify-between ${
                  selectedCategory === "admin"
                    ? "bg-blue-950/70 border-blue-500 shadow-md shadow-blue-500/20 ring-1 ring-blue-500"
                    : "bg-slate-900/60 border-slate-800 hover:border-slate-700 text-slate-400"
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xl">🛡️</span>
                  {selectedCategory === "admin" && (
                    <span className="w-2 h-2 rounded-full bg-blue-400 shadow-[0_0_8px_#60a5fa]" />
                  )}
                </div>
                <div>
                  <div className={`text-xs font-bold ${selectedCategory === "admin" ? "text-white" : "text-slate-300"}`}>
                    Administrator
                  </div>
                  <div className="text-[10px] text-slate-400 leading-tight mt-0.5">
                    Command triage, dispatch & logistics
                  </div>
                </div>
              </button>

              {/* Option 3: Service Provider */}
              <button
                type="button"
                onClick={() => handleCategoryChange("service_provider")}
                className={`p-3 rounded-xl border text-left transition cursor-pointer flex flex-col justify-between ${
                  selectedCategory === "service_provider"
                    ? "bg-amber-950/70 border-amber-500 shadow-md shadow-amber-500/20 ring-1 ring-amber-500"
                    : "bg-slate-900/60 border-slate-800 hover:border-slate-700 text-slate-400"
                }`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xl">🚑</span>
                  {selectedCategory === "service_provider" && (
                    <span className="w-2 h-2 rounded-full bg-amber-400 shadow-[0_0_8px_#fbbf24]" />
                  )}
                </div>
                <div>
                  <div className={`text-xs font-bold ${selectedCategory === "service_provider" ? "text-white" : "text-slate-300"}`}>
                    Service Provider
                  </div>
                  <div className="text-[10px] text-slate-400 leading-tight mt-0.5">
                    Medic, Fire, NDRF field responder HUD
                  </div>
                </div>
              </button>
            </div>
          </div>

          {/* Quick 1-Click Demo Login Presets (not offered for Administrator: staff use real authentication) */}
          {mode === "login" && selectedCategory !== "admin" && (
            <div className="p-3 bg-slate-900/80 rounded-xl border border-slate-800">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-amber-400 flex items-center gap-1.5">
                  <span>⚡</span> Quick One-Click Demo Login:
                </span>
                <span className="text-[10px] text-slate-400">Instant test accounts</span>
              </div>
              <div className="flex flex-wrap gap-2">
                {demoPresets.map((u) => (
                  <button
                    key={u.id}
                    type="button"
                    onClick={() => handleQuickDemoLogin(u)}
                    className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700/80 hover:border-sky-500 px-2.5 py-1.5 rounded-lg transition cursor-pointer flex items-center gap-1.5"
                    title={`Log in as ${u.name} (${u.role})`}
                  >
                    <span className="font-semibold text-white">{u.name}</span>
                    <span className="text-[10px] text-sky-400 font-mono">
                      {u.role.split("/")[0]}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Feedback Alerts */}
          {errorMsg && (
            <div className="p-3 bg-red-950/80 border border-red-700/60 rounded-xl text-red-200 text-xs flex items-center gap-2 animate-shake">
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

          {/* ============ SIGN IN FORM ============ */}
          {mode === "login" && selectedCategory === "admin" ? (
            <StaffSignIn />
          ) : mode === "login" ? (
            <form onSubmit={handleLoginSubmit} className="space-y-3.5">
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
                      ? "commander@resq.gov.in or NDMA-HQ-01"
                      : "medic@resq.gov.in or EMS-MED-07"
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
                  placeholder="Enter your password (e.g. admin123password)"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
              </div>

              <div className="pt-2 flex items-center gap-3">
                <button
                  type="submit"
                  className="flex-1 bg-sky-600 hover:bg-sky-500 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-sky-600/30 cursor-pointer flex items-center justify-center gap-2"
                >
                  <span>Sign In as {selectedCategory === "user" ? "Citizen" : selectedCategory === "admin" ? "Administrator" : "Service Provider"}</span>
                  <span>→</span>
                </button>
              </div>
            </form>
          ) : (
            /* ============ SIGN UP FORM ============ */
            <form onSubmit={handleSignupSubmit} className="space-y-3.5">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Full Name</label>
                  <input
                    type="text"
                    required
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="e.g. Sunil Kumar"
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Phone Number</label>
                  <input
                    type="tel"
                    required
                    value={signupPhone}
                    onChange={(e) => setSignupPhone(e.target.value)}
                    placeholder="+91 98765 43210"
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">Email Address</label>
                <input
                  type="email"
                  required
                  value={signupEmail}
                  onChange={(e) => setSignupEmail(e.target.value)}
                  placeholder="name@domain.gov.in"
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
              </div>

              {selectedCategory !== "user" && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">
                      Operational Sub-Role
                    </label>
                    <select
                      value={specificRole}
                      onChange={(e) => setSpecificRole(e.target.value as UserRole)}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs text-white focus:outline-none focus:border-sky-500"
                    >
                      {selectedCategory === "admin" ? (
                        <>
                          <option value="Command Officer / Incident Commander">Incident Commander (NDMA)</option>
                          <option value="Dispatcher">Emergency Dispatcher (ERSS 112)</option>
                          <option value="System Administrator">System Administrator (DRCH)</option>
                        </>
                      ) : (
                        <>
                          <option value="Medic / Ambulance Team">Ambulance Paramedic (EMS 108)</option>
                          <option value="Firefighter / Fire Service Officer">Fire & Rescue Officer</option>
                          <option value="NDRF / SDRF Team Leader or Responder">NDRF Rescue Team Leader</option>
                          <option value="Logistics Officer">Disaster Logistics & Relief Officer</option>
                        </>
                      )}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-slate-300 mb-1">Badge / Callsign</label>
                    <input
                      type="text"
                      value={badgeNumber}
                      onChange={(e) => setBadgeNumber(e.target.value)}
                      placeholder={selectedCategory === "admin" ? "NDMA-HQ-05" : "AMB-11 / FIRE-09"}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                    />
                  </div>
                </div>
              )}

              <div>
                <label className="block text-xs font-semibold text-slate-300 mb-1">
                  Agency / Organization
                </label>
                <input
                  type="text"
                  value={agency}
                  onChange={(e) => setAgency(e.target.value)}
                  placeholder={
                    selectedCategory === "user"
                      ? "Resident / Public Citizen"
                      : "e.g. State Disaster Response Force"
                  }
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Password</label>
                  <input
                    type="password"
                    required
                    value={signupPassword}
                    onChange={(e) => setSignupPassword(e.target.value)}
                    placeholder="Min 6 characters"
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-slate-300 mb-1">Confirm Password</label>
                  <input
                    type="password"
                    required
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Re-type password"
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"
                  />
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  className="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-bold py-2.5 px-4 rounded-xl text-sm transition shadow-lg shadow-emerald-600/30 cursor-pointer flex items-center justify-center gap-2"
                >
                  <span>Register & Enter Portal</span>
                  <span>→</span>
                </button>
              </div>
            </form>
          )}

          {/* Social Google Sign-In */}
          <GoogleSignInButton mode={mode} onSuccess={onClose} onError={setErrorMsg} />

          {/* Guest / Public Mode Fallback */}
          <div className="pt-2 border-t border-slate-800 flex items-center justify-between text-xs text-slate-400">
            <span>Want to browse public disaster overview first?</span>
            <button
              type="button"
              onClick={onClose}
              className="text-sky-400 hover:text-sky-300 font-semibold underline underline-offset-2 cursor-pointer"
            >
              Continue to General Dashboard →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
