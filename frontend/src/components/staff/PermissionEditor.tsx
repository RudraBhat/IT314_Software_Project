"use client";

export const ALL_PERMISSIONS = ["PUBLISHER", "MODERATOR", "CLOSURE", "DISPATCH", "SUPERVISOR"] as const;

export const PERMISSION_DESC: Record<string, string> = {
  PUBLISHER: "Publish incidents & public alerts",
  MODERATOR: "Verify/reject evidence uploads",
  CLOSURE: "Close & archive incidents",
  DISPATCH: "Assign & dispatch responder units",
  SUPERVISOR: "Full oversight + staff management",
};

/** Toggle chips for Disaster Management permissions. `available` limits what can be granted. */
export function PermissionEditor({
  value,
  onChange,
  available = ALL_PERMISSIONS,
}: {
  value: string[];
  onChange: (perms: string[]) => void;
  available?: readonly string[];
}) {
  const toggle = (p: string) => onChange(value.includes(p) ? value.filter((x) => x !== p) : [...value, p]);
  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="Permissions">
      {ALL_PERMISSIONS.filter((p) => available.includes(p)).map((p) => {
        const active = value.includes(p);
        return (
          <button
            key={p}
            type="button"
            onClick={() => toggle(p)}
            title={PERMISSION_DESC[p]}
            aria-pressed={active}
            className={`cursor-pointer select-none rounded-lg border px-3 py-1.5 text-xs font-semibold transition ${
              active
                ? "border-sky-500/60 bg-sky-500/20 text-sky-300"
                : "border-border bg-surface-muted text-muted hover:border-sky-500/40 hover:text-foreground"
            }`}
          >
            {p}
          </button>
        );
      })}
    </div>
  );
}
