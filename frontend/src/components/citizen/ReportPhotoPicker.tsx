"use client";

import { useEffect, useRef, useState } from "react";

import { ATTACHMENT_LIMITS } from "@/services/citizenApi";

const THUMB_WIDTH = 160;
const THUMB_HEIGHT = 120;
const MAX_MB = ATTACHMENT_LIMITS.maxBytes / (1024 * 1024);

/**
 * Local preview of a picked photo. The image is decoded and drawn on a canvas, so no URL or markup
 * derived from the user's file is ever placed in the DOM.
 */
function PhotoThumbnail({ file }: { file: File }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    let cancelled = false;
    let bitmap: ImageBitmap | null = null;
    createImageBitmap(file)
      .then((decoded) => {
        bitmap = decoded;
        const ctx = canvasRef.current?.getContext("2d");
        if (cancelled || !ctx) return;
        // Cover-crop to the thumbnail, keeping the centre of the photo.
        const scale = Math.max(THUMB_WIDTH / decoded.width, THUMB_HEIGHT / decoded.height);
        const w = decoded.width * scale;
        const h = decoded.height * scale;
        ctx.clearRect(0, 0, THUMB_WIDTH, THUMB_HEIGHT);
        ctx.drawImage(decoded, (THUMB_WIDTH - w) / 2, (THUMB_HEIGHT - h) / 2, w, h);
      })
      .catch(() => {
        // Undecodable in this browser: the grey placeholder stays; the server still checks the file.
      });
    return () => {
      cancelled = true;
      bitmap?.close();
    };
  }, [file]);
  return (
    <canvas
      ref={canvasRef}
      width={THUMB_WIDTH}
      height={THUMB_HEIGHT}
      role="img"
      aria-label={`Preview of ${file.name}`}
      className="h-20 w-full rounded bg-slate-100"
    />
  );
}

type Props = {
  /** id for the file input, so the field's label can point at it. */
  inputId: string;
  label: string;
  photos: File[];
  onChange: (photos: File[]) => void;
  disabled?: boolean;
};

/**
 * Optional photos for a new incident report (NU-FR-05, #180): file picker or drag-and-drop, thumbnail
 * previews with per-photo removal. Files are checked here for a quick answer; the backend checks the
 * real bytes again and strips metadata. Photos are uploaded after the report is filed
 * (see `uploadReportPhotos`).
 */
export function ReportPhotoPicker({ inputId, label, photos, onChange, disabled = false }: Props) {
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const helpId = `${inputId}-help`;
  const full = photos.length >= ATTACHMENT_LIMITS.maxFiles;

  function add(chosen: File[]) {
    if (chosen.length === 0) return;
    const wrongType = chosen.find((f) => !ATTACHMENT_LIMITS.types.includes(f.type));
    if (wrongType) return setError(`${wrongType.name} is not a JPEG, PNG or WebP image.`);
    const tooBig = chosen.find((f) => f.size > ATTACHMENT_LIMITS.maxBytes);
    if (tooBig) return setError(`${tooBig.name} is larger than ${MAX_MB} MB.`);
    setError(photos.length + chosen.length > ATTACHMENT_LIMITS.maxFiles ? `At most ${ATTACHMENT_LIMITS.maxFiles} photos.` : null);
    onChange([...photos, ...chosen].slice(0, ATTACHMENT_LIMITS.maxFiles));
  }

  return (
    <div>
      <label htmlFor={inputId} className="block text-xs font-bold text-slate-800 uppercase tracking-wider mb-2">
        {label}
      </label>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled && !full) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (!disabled && !full) add(Array.from(e.dataTransfer.files));
        }}
        className={`rounded-xl border-2 border-dashed p-4 text-center transition ${
          dragOver ? "border-sky-500 bg-sky-50" : "border-slate-300 bg-slate-50"
        }`}
      >
        <p className="text-xs text-slate-600 mb-2" aria-hidden="true">
          Drag photos here, or
        </p>
        <input
          id={inputId}
          type="file"
          accept={ATTACHMENT_LIMITS.types.join(",")}
          multiple
          aria-describedby={helpId}
          disabled={disabled || full}
          onChange={(e) => {
            const chosen = Array.from(e.target.files ?? []);
            e.target.value = "";
            add(chosen);
          }}
          className="mx-auto block max-w-full text-xs text-slate-700 file:mr-3 file:rounded-lg file:border-0 file:bg-white file:px-3 file:py-2 file:text-slate-700 file:shadow-xs hover:file:bg-slate-100 disabled:opacity-50"
        />
      </div>
      <p id={helpId} className="text-xs text-slate-500 mt-1">
        Up to {ATTACHMENT_LIMITS.maxFiles} JPEG, PNG or WebP photos, {MAX_MB} MB each. On a phone you can take a photo with the camera. Location and camera details are removed from photos, and moderators review them before they are used.
      </p>
      {error && <p role="alert" className="text-xs text-red-600 mt-1">{error}</p>}
      {photos.length > 0 && (
        <ul className="mt-3 grid grid-cols-3 sm:grid-cols-5 gap-2" aria-label="Selected photos">
          {photos.map((photo, index) => (
            <li key={`${photo.name}-${photo.size}-${index}`} className="rounded-lg border border-slate-200 bg-white p-1.5 text-xs text-slate-800">
              <PhotoThumbnail file={photo} />
              <div className="mt-1 truncate" title={photo.name}>{photo.name}</div>
              <button
                type="button"
                disabled={disabled}
                onClick={() => {
                  onChange(photos.filter((_, i) => i !== index));
                  setError(null);
                }}
                className="mt-0.5 text-red-600 hover:text-red-800 cursor-pointer disabled:opacity-50"
                aria-label={`Remove ${photo.name}`}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
