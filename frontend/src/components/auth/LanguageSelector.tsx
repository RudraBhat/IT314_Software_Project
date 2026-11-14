"use client";

import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";

import { AUTH_LANGUAGES, useAuthLanguage, type AuthLanguage } from "./AuthLanguage";

function matches(query: string, language: (typeof AUTH_LANGUAGES)[number]): boolean {
  const q = query.trim().toLocaleLowerCase();
  if (!q) return true;
  return [language.englishName, language.nativeName, language.code].some((name) =>
    name.toLocaleLowerCase().includes(q),
  );
}

/**
 * Searchable language picker (issue #95), following the WAI-ARIA combobox + listbox pattern:
 * a button opens a popup with a search box (role="combobox") that filters a listbox.
 * Keyboard: ↑/↓ move, Home/End jump, Enter selects, Escape closes and returns focus, Tab closes.
 * The choice is stored by AuthLanguageProvider, so it persists across navigation and refresh.
 */
export function LanguageSelector() {
  const { language, setLanguage, copy } = useAuthLanguage();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const baseId = useId();
  const labelId = `${baseId}-label`;
  const listboxId = `${baseId}-listbox`;
  const optionId = (code: string) => `${baseId}-option-${code}`;

  const current = AUTH_LANGUAGES.find((l) => l.code === language) ?? AUTH_LANGUAGES[0];
  const results = useMemo(() => AUTH_LANGUAGES.filter((l) => matches(query, l)), [query]);
  const active = results[Math.min(activeIndex, results.length - 1)];

  useEffect(() => {
    if (!open) return;
    inputRef.current?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  function openPopup() {
    setQuery("");
    setActiveIndex(Math.max(0, AUTH_LANGUAGES.findIndex((l) => l.code === language)));
    setOpen(true);
  }

  function close(returnFocus: boolean) {
    setOpen(false);
    if (returnFocus) buttonRef.current?.focus();
  }

  function choose(code: AuthLanguage) {
    setLanguage(code);
    close(true);
  }

  function onSearchKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    const last = results.length - 1;
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActiveIndex((i) => (i >= last ? 0 : i + 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        setActiveIndex((i) => (i <= 0 ? last : i - 1));
        break;
      case "Home":
        event.preventDefault();
        setActiveIndex(0);
        break;
      case "End":
        event.preventDefault();
        setActiveIndex(Math.max(0, last));
        break;
      case "Enter":
        event.preventDefault();
        if (active) choose(active.code);
        break;
      case "Escape":
        event.preventDefault();
        close(true);
        break;
      case "Tab":
        close(false);
        break;
    }
  }

  return (
    <div ref={rootRef} className="relative flex items-center justify-end gap-2">
      <span id={labelId} className="text-sm font-semibold text-slate-700">
        {copy.language}
      </span>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-labelledby={`${labelId} ${baseId}-value`}
        onClick={() => (open ? close(false) : openPopup())}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            openPopup();
          }
        }}
        className="flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus-visible:ring-4 focus-visible:ring-sky-300"
      >
        <span id={`${baseId}-value`} lang={current.code}>
          {current.nativeName}
        </span>
        <span aria-hidden className="text-xs text-slate-500">▾</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-xl border border-slate-200 bg-white p-2 shadow-xl">
          <input
            ref={inputRef}
            type="search"
            role="combobox"
            aria-label={copy.searchLanguages}
            aria-autocomplete="list"
            aria-expanded="true"
            aria-controls={listboxId}
            aria-activedescendant={active ? optionId(active.code) : undefined}
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            onKeyDown={onSearchKeyDown}
            placeholder={copy.searchLanguages}
            autoComplete="off"
            className="mb-2 min-h-11 w-full rounded-lg border border-slate-300 px-3 text-base text-slate-900 focus:border-sky-600 focus:outline-none focus:ring-2 focus:ring-sky-200"
          />
          <ul id={listboxId} role="listbox" aria-labelledby={labelId} className="max-h-64 overflow-y-auto">
            {results.map((option) => {
              const selected = option.code === language;
              const highlighted = option.code === active?.code;
              return (
                <li
                  key={option.code}
                  id={optionId(option.code)}
                  role="option"
                  aria-selected={selected}
                  onPointerDown={(event) => event.preventDefault()}
                  onClick={() => choose(option.code)}
                  onPointerMove={() => setActiveIndex(results.indexOf(option))}
                  className={`flex min-h-11 cursor-pointer items-center justify-between rounded-lg px-3 text-base ${
                    highlighted ? "bg-sky-100 text-sky-950" : "text-slate-800"
                  }`}
                >
                  <span>
                    <span lang={option.code} className="font-semibold">{option.nativeName}</span>
                    {option.nativeName !== option.englishName && (
                      <span className="ml-2 text-sm text-slate-500">{option.englishName}</span>
                    )}
                  </span>
                  {selected && <span aria-hidden className="text-sky-700">✓</span>}
                </li>
              );
            })}
          </ul>
          {results.length === 0 && (
            <p role="status" className="px-3 py-2 text-sm text-slate-600">
              {copy.noLanguageMatch}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
