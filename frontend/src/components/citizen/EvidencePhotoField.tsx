"use client";

import { useId, useRef, useState } from "react";

import type { EvidencePolicy } from "@/services/citizenApi";

const TYPE_LABEL: Record<string, string> = { "image/jpeg": "JPEG", "image/png": "PNG" };

type Props = {
  policy: EvidencePolicy;
  value: File | null;
  onChange: (file: File | null) => void;
};

/**
 * Optional photo for a new report (issue #68). Shown only when evidence storage is configured.
 * The file is checked here for a quick answer; the backend checks the real bytes again.
 */
export function EvidencePhotoField({ policy, value, onChange }: Props) {
  const inputId = useId();
  const helpId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const maxMb = Math.floor(policy.max_bytes / (1024 * 1024));
  const types = policy.allowed_types.map((t) => TYPE_LABEL[t] ?? t).join(" or ");

  function select(file: File | undefined) {
    setError(null);
    if (!file) return onChange(null);
    if (!policy.allowed_types.includes(file.type)) {
      setError(`Choose a ${types} photo.`);
    } else if (file.size > policy.max_bytes) {
      setError(`The photo is larger than ${maxMb} MB.`);
    } else {
      return onChange(file);
    }
    onChange(null);
    if (inputRef.current) inputRef.current.value = "";
  }

  return (
    <div>
      <label htmlFor={inputId} className="block text-xs font-bold text-slate-200 uppercase tracking-wider mb-2">
        Photo (optional)
      </label>
      <input
        ref={inputRef}
        id={inputId}
        type="file"
        accept={policy.allowed_types.join(",")}
        aria-describedby={helpId}
        aria-invalid={error ? true : undefined}
        onChange={(e) => select(e.target.files?.[0])}
        className="block w-full text-xs text-slate-300 file:mr-3 file:min-h-[40px] file:rounded-lg file:border-0 file:bg-slate-800 file:px-4 file:text-xs file:font-semibold file:text-slate-100 hover:file:bg-slate-700"
      />
      <p id={helpId} className="mt-1.5 text-[11px] text-slate-400">
        {types}, up to {maxMb} MB. Only the response team sees it, after a moderator checks it.
      </p>
      {value && !error && (
        <p className="mt-1 text-[11px] text-emerald-300">
          Selected: {value.name} ({Math.ceil(value.size / 1024)} KB)
        </p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-[11px] font-medium text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
