"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import * as CitizenApi from "@/services/citizenApi";
import { type LanguageCode, TRANSLATIONS } from "@/lib/citizenI18n";

const POLL_MS = 20_000;

/** The citizen's chosen dashboard language (saved by the dashboard), English if none. */
function savedLanguage(): LanguageCode {
  try {
    const saved = localStorage.getItem("resq_lang");
    if (saved === "en" || saved === "hi" || saved === "gu") return saved;
  } catch {
    // storage unavailable
  }
  return "en";
}

/**
 * In-app notification bell for signed-in citizens. It lives in the shared header, so it stays on every
 * page (dashboard, safety, how to use, about, donate...) instead of only on the dashboard. It loads the
 * citizen's notifications, refreshes them every 20 seconds while the page is open, and lets the citizen
 * mark one or all as read.
 */
export function NotificationBell() {
  const [items, setItems] = useState<CitizenApi.InAppNotification[]>([]);
  const [open, setOpen] = useState(false);
  const [lang, setLang] = useState<LanguageCode>("en");
  const boxRef = useRef<HTMLDivElement>(null);
  const t = TRANSLATIONS[lang];

  const load = useCallback(async () => {
    const res = await CitizenApi.fetchMyNotifications();
    if (res.data?.items) setItems(res.data.items);
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- read the saved language and load once after mount
    setLang(savedLanguage());
    void load();
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // Close the dropdown on an outside click or Escape.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const unread = items.filter((n) => !n.read_at).length;

  async function markRead(id: string) {
    const res = await CitizenApi.markNotificationRead(id);
    if (!res.error) {
      setItems((prev) => prev.map((n) => (n.notification_id === id ? { ...n, read_at: new Date().toISOString() } : n)));
    }
  }

  async function markAllRead() {
    const res = await CitizenApi.markAllNotificationsRead();
    if (!res.error) {
      const now = new Date().toISOString();
      setItems((prev) => prev.map((n) => ({ ...n, read_at: n.read_at || now })));
    }
  }

  return (
    <div className="relative" ref={boxRef}>
      <button
        onClick={() => {
          setLang(savedLanguage());
          setOpen((v) => !v);
        }}
        className="relative cursor-pointer rounded-full p-1.5 text-sky-100 transition hover:bg-white/10"
        title={t.notifications}
        aria-label={unread ? `${t.notifications}: ${unread} unread` : t.notifications}
        aria-expanded={open}
      >
        <svg className="size-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden>
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"
          />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex size-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 text-slate-900 shadow-xl sm:w-96">
          <div className="mb-2 flex items-center justify-between border-b border-slate-100 pb-2">
            <span className="text-xs font-bold uppercase tracking-wider text-slate-600">
              {t.notifications} ({unread} unread)
            </span>
            <div className="flex items-center gap-2">
              {unread > 0 && (
                <button onClick={markAllRead} className="text-[11px] font-semibold text-sky-700 hover:text-sky-900">
                  {t.markAllRead}
                </button>
              )}
              <button onClick={() => setOpen(false)} className="text-xs text-slate-400 hover:text-slate-600" aria-label="Close notifications">
                ✕
              </button>
            </div>
          </div>
          {items.length === 0 ? (
            <p className="py-6 text-center text-xs text-slate-400">{t.noNotifications}</p>
          ) : (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {items.map((item) => {
                const isUnread = !item.read_at;
                return (
                  <div
                    key={item.notification_id}
                    className={`rounded-lg border p-2.5 text-xs transition ${
                      isUnread ? "border-sky-200 bg-sky-50/60" : "border-slate-100 bg-slate-50 opacity-80"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-1">
                      <span className="font-semibold text-slate-900">{item.title}</span>
                      {isUnread && (
                        <button
                          onClick={() => markRead(item.notification_id)}
                          className="shrink-0 text-[10px] font-medium text-sky-600 hover:text-sky-800"
                        >
                          {t.markRead}
                        </button>
                      )}
                    </div>
                    <p className="mt-1 text-[11px] text-slate-600">{item.body}</p>
                    <span className="mt-1 block text-[10px] text-slate-400">
                      {new Date(item.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
