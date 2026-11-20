import { PERMISSION_INFO, sortPermissions } from "@/lib/format";

/**
 * Disaster Management permissions as coloured chips, most senior first. Hovering a chip (or reading it
 * with a screen reader) gives what that permission allows.
 */
export function PermissionChips({ permissions, empty = "No permissions assigned" }: { permissions: readonly string[]; empty?: string }) {
  if (!permissions.length) return <span className="text-[11px] italic text-muted">{empty}</span>;
  return (
    <ul className="flex flex-wrap gap-1.5" aria-label="Permissions">
      {sortPermissions(permissions).map((p) => {
        const info = PERMISSION_INFO[p];
        return (
          <li
            key={p}
            title={info?.description}
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ring-1 ${info?.tone ?? "bg-slate-100 text-slate-700 ring-slate-200"}`}
          >
            <span aria-hidden>{info?.icon ?? "•"}</span>
            {info?.label ?? p}
            {info && <span className="sr-only">: {info.description}</span>}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * Compact role summary for the dark header: the most senior permission plus a count, opening a light
 * panel that lists every permission with what it allows. Uses <details>, so it works without JavaScript.
 */
export function HeaderRoleMenu({ permissions }: { permissions: readonly string[] }) {
  const sorted = sortPermissions(permissions);
  if (!sorted.length) return <span className="text-[10px] text-sky-200/80">Disaster Management</span>;
  const top = PERMISSION_INFO[sorted[0]]?.label ?? sorted[0];
  return (
    <details className="group relative">
      <summary className="inline-flex cursor-pointer list-none items-center gap-1 rounded text-[10px] font-semibold text-sky-200 hover:text-white [&::-webkit-details-marker]:hidden">
        {top}
        {sorted.length > 1 && <span className="rounded-full bg-white/15 px-1.5">+{sorted.length - 1}</span>}
        <span aria-hidden className="transition group-open:rotate-180">▾</span>
        <span className="sr-only"> (show all permissions)</span>
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-3 text-left text-slate-800 shadow-xl">
        <p className="mb-2 text-[11px] font-bold uppercase tracking-wide text-slate-500">Your permissions</p>
        <ul className="space-y-2">
          {sorted.map((p) => {
            const info = PERMISSION_INFO[p];
            return (
              <li key={p} className="flex items-start gap-2">
                <span
                  className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full text-xs ring-1 ${info?.tone ?? "bg-slate-100 ring-slate-200"}`}
                  aria-hidden
                >
                  {info?.icon ?? "•"}
                </span>
                <span>
                  <span className="block text-sm font-semibold">{info?.label ?? p}</span>
                  {info && <span className="block text-xs text-slate-500">{info.description}</span>}
                </span>
              </li>
            );
          })}
        </ul>
      </div>
    </details>
  );
}
