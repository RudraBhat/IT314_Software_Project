"use client";

import Link from "next/link";
import React, { useEffect, useState } from "react";

import { signOut } from "@/app/login/actions";
import { UnifiedSiteHeader } from "@/components/navigation/UnifiedSiteHeader";
import { changePassword, deleteAccount, fetchProfile, updateProfile, type ProfileData } from "@/services/citizenApi";

const LANGUAGES: { code: "en" | "hi" | "gu"; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "gu", label: "ગુજરાતી" },
];

const field =
  "w-full min-h-[44px] rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-400";
const button =
  "min-h-[44px] rounded-lg bg-sky-600 px-5 py-2 text-sm font-bold text-white transition hover:bg-sky-500 disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300";

/** Citizen account: name, phone, language, alert preferences and password. The email is the sign-in identity and is shown, not edited. */
export default function AccountPage() {
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState<"en" | "hi" | "gu">("en");
  const [emailAlerts, setEmailAlerts] = useState(true);
  const [smsAlerts, setSmsAlerts] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState<{ ok: boolean; text: string } | null>(null);

  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [changing, setChanging] = useState(false);
  const [passwordError, setPasswordError] = useState<string | null>(null);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function apply(p: ProfileData) {
    setProfile(p);
    setFullName(p.full_name);
    setPhone(p.phone ?? "");
    setLanguage(p.preferred_language);
    setEmailAlerts(p.alerts.email);
    setSmsAlerts(p.alerts.sms);
  }

  useEffect(() => {
    fetchProfile().then((res) => {
      if (res.data) apply(res.data);
      else setLoadError(res.error ?? "Could not load your account.");
    });
  }, []);

  async function onSave(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setSaveMessage(null);
    const res = await updateProfile({
      full_name: fullName,
      phone,
      preferred_language: language,
      email_alerts: emailAlerts,
      sms_alerts: smsAlerts,
    });
    setSaving(false);
    if (res.data) {
      apply(res.data);
      setSaveMessage({ ok: true, text: "Saved." });
    } else {
      setSaveMessage({ ok: false, text: res.error ?? "Could not save." });
    }
  }

  async function onChangePassword(event: React.FormEvent) {
    event.preventDefault();
    setChanging(true);
    setPasswordError(null);
    const res = await changePassword(currentPassword, newPassword);
    if (res.error) {
      setChanging(false);
      setPasswordError(res.error);
      return;
    }
    // The server ended every session, so sign out here and ask the person to sign in with the new password.
    await signOut();
  }

  async function onDelete(event: React.FormEvent) {
    event.preventDefault();
    if (!window.confirm("Delete your account? Your details are erased and this cannot be undone.")) return;
    setDeleting(true);
    setDeleteError(null);
    const res = await deleteAccount(deletePassword);
    if (res.error) {
      setDeleting(false);
      setDeleteError(res.error);
      return;
    }
    await signOut();
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <UnifiedSiteHeader activeHref="/account" />

      <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 p-4 sm:p-6">
        {loadError && (
          <div role="alert" className="rounded-xl border border-red-700/60 bg-red-950/60 p-4 text-sm text-red-200">
            {loadError}{" "}
            <Link href="/login?next=/account" className="underline">Sign in</Link>
          </div>
        )}

        {profile && (
          <>
            <form onSubmit={onSave} className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-5 sm:p-6">
              <h1 className="text-xl font-bold text-white">Your details</h1>
              <div>
                <label htmlFor="acc-email" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">Email (sign-in)</label>
                <input id="acc-email" value={profile.email} readOnly className={`${field} opacity-70`} />
              </div>
              <div>
                <label htmlFor="acc-name" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">Full name</label>
                <input id="acc-name" value={fullName} onChange={(e) => setFullName(e.target.value)} required maxLength={120} className={field} />
              </div>
              <div>
                <label htmlFor="acc-phone" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">Phone</label>
                <input id="acc-phone" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+919876543210" className={field} />
              </div>
              <div>
                <label htmlFor="acc-lang" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">Preferred language</label>
                <select id="acc-lang" value={language} onChange={(e) => setLanguage(e.target.value as "en" | "hi" | "gu")} className={field}>
                  {LANGUAGES.map((l) => (
                    <option key={l.code} value={l.code}>{l.label}</option>
                  ))}
                </select>
              </div>
              <fieldset className="space-y-2">
                <legend className="mb-1 text-xs font-bold uppercase tracking-wider text-slate-300">Alerts</legend>
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input type="checkbox" checked disabled /> In-app notifications (always on)
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={emailAlerts} onChange={(e) => setEmailAlerts(e.target.checked)} /> Email alerts
                </label>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={smsAlerts} onChange={(e) => setSmsAlerts(e.target.checked)} /> SMS alerts
                </label>
                <p className="text-xs text-slate-400">Email alerts send a copy of each notification to your email address. SMS is saved as a preference but is not available yet. In-app notifications always work.</p>
              </fieldset>
              <div className="flex items-center gap-3">
                <button type="submit" disabled={saving} className={button}>{saving ? "Saving…" : "Save changes"}</button>
                {saveMessage && (
                  <span role="status" className={`text-sm ${saveMessage.ok ? "text-emerald-400" : "text-red-300"}`}>{saveMessage.text}</span>
                )}
              </div>
            </form>

            {!profile.has_password && (
              <div role="note" className="rounded-2xl border border-sky-800/60 bg-sky-950/40 p-5 text-sm text-sky-100 sm:p-6">
                <h2 className="mb-1 text-xl font-bold text-white">Password</h2>
                You sign in with Google, so your account has no password yet. To change it or delete your account, first set a password with{" "}
                <Link href="/forgot-password" className="font-semibold underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300">Forgot password</Link>
                ; the link goes to {profile.email}.
              </div>
            )}
            {profile.has_password && (
            <form onSubmit={onChangePassword} className="space-y-4 rounded-2xl border border-slate-800 bg-slate-900 p-5 sm:p-6">
              <h2 className="text-xl font-bold text-white">Change password</h2>
              <p className="text-xs text-slate-400">At least 8 characters with a digit and a special symbol. You will be signed out everywhere and sign in again.</p>
              <div>
                <label htmlFor="acc-current" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">Current password</label>
                <input id="acc-current" type="password" autoComplete="current-password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} required className={field} />
              </div>
              <div>
                <label htmlFor="acc-new" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">New password</label>
                <input id="acc-new" type="password" autoComplete="new-password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} required className={field} />
              </div>
              {passwordError && <p role="alert" className="text-sm text-red-300">{passwordError}</p>}
              <button type="submit" disabled={changing} className={button}>{changing ? "Changing…" : "Change password"}</button>
            </form>
            )}
            {profile.has_password && (
            <form onSubmit={onDelete} className="space-y-4 rounded-2xl border border-red-900/60 bg-slate-900 p-5 sm:p-6">
              <h2 className="text-xl font-bold text-white">Delete account</h2>
              <p className="text-xs text-slate-400">
                Your name, email, phone and photos are erased and you are signed out everywhere. Reports you filed stay on record for the
                response audit trail without your identity. You can only delete your account when none of your reports is still open.
              </p>
              <div>
                <label htmlFor="acc-delete" className="mb-1 block text-xs font-bold uppercase tracking-wider text-slate-300">Confirm with your password</label>
                <input id="acc-delete" type="password" autoComplete="current-password" value={deletePassword} onChange={(e) => setDeletePassword(e.target.value)} required className={field} />
              </div>
              {deleteError && <p role="alert" className="text-sm text-red-300">{deleteError}</p>}
              <button type="submit" disabled={deleting} className="min-h-[44px] rounded-lg bg-red-700 px-5 py-2 text-sm font-bold text-white transition hover:bg-red-600 disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-300">
                {deleting ? "Deleting…" : "Delete my account"}
              </button>
            </form>
            )}
          </>
        )}
      </main>
    </div>
  );
}
