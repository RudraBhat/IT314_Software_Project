import Link from "next/link";
import type { ReactNode } from "react";

const NAVY = "#0C4A75";
const SKY = "#38BDF8";
const RED = "#DC2626";

/** Radar "Q" (final identity: Q-Radar). Drawn in a 100x100 box; `dark` adds the white ring on the alert dot. */
function Radar({ ink, id, dark }: { ink: string; id: string; dark: boolean }) {
  return (
    <>
      <defs>
        <mask id={id} maskUnits="userSpaceOnUse" x="-20" y="-20" width="140" height="140">
          <rect x="-20" y="-20" width="140" height="140" fill="#fff" />
          <circle cx="25.96" cy="25.96" r="12.5" fill="#000" />
          <path d="M64.14 64.14L106.57 106.57" stroke="#000" strokeWidth="21" fill="none" />
        </mask>
      </defs>
      <circle cx="50" cy="50" r="34" fill="none" stroke={ink} strokeWidth="12" mask={`url(#${id})`} />
      <path d="M50 50L72.47 35.96A26.5 26.5 0 0 1 68.74 68.74Z" fill={SKY} stroke={SKY} strokeWidth="2" strokeLinejoin="round" />
      <path d="M50 50L84.29 84.29" fill="none" stroke={ink} strokeWidth="12" strokeLinecap="round" />
      <circle cx="25.96" cy="25.96" r="9" fill={RED} {...(dark ? { stroke: "#FFFFFF", strokeWidth: 3 } : {})} />
    </>
  );
}

/** Full ResQ lockup (R, E, S drawn as strokes + radar Q). `variant="dark"` is for navy/dark backgrounds. */
export function Logo({ variant = "dark", className = "h-8 w-auto" }: { variant?: "light" | "dark"; className?: string }) {
  const dark = variant === "dark";
  const ink = dark ? "#FFFFFF" : NAVY;
  const id = `rq-${variant}`;
  return (
    <svg viewBox="-1 -67 209 72" className={className} role="img" aria-label="ResQ" xmlns="http://www.w3.org/2000/svg">
      <g fill="none" stroke={ink} strokeWidth="9.67" strokeLinejoin="miter">
        <path d="M4.84 0V-64" />
        <path d="M4.84 -59.16H24A14.16 14.16 0 0 1 24 -30.84H4.84" />
        <path d="M21 -30.84L42 0" />
        <path d="M57.84 -23.5H95.16A18.66 18.66 0 1 0 90.8 -11.5" />
        <path d="M127.81 -38.18A9.33 9.33 0 1 0 120.17 -23.5A9.33 9.33 0 1 1 112.52 -8.82" />
      </g>
      <g transform="translate(132.94 -72.3) scale(0.806)">
        <Radar ink={ink} id={id} dark={dark} />
      </g>
    </svg>
  );
}

/** Standalone radar-Q symbol (no wordmark). */
export function LogoMark({ variant = "dark", className = "size-9" }: { variant?: "light" | "dark"; className?: string }) {
  const dark = variant === "dark";
  return (
    <svg viewBox="0 0 100 100" className={className} role="img" aria-label="ResQ" xmlns="http://www.w3.org/2000/svg">
      <Radar ink={dark ? "#FFFFFF" : NAVY} id={`rqm-${variant}`} dark={dark} />
    </svg>
  );
}

export const DEFAULT_BRAND_SUBTITLE = "Gujarat Emergency Portal";

/** Single brand lockup used by every header so the logo is identical everywhere. */
export function Brand({
  href = "/",
  subtitle = DEFAULT_BRAND_SUBTITLE,
  size = "md",
}: {
  href?: string;
  subtitle?: string;
  size?: "sm" | "md";
}) {
  return (
    <Link
      href={href}
      className="flex min-w-0 items-center gap-3 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300"
      aria-label="ResQ home"
    >
      <Logo variant="dark" className={size === "sm" ? "h-7 w-auto shrink-0" : "h-8 w-auto shrink-0"} />
      {subtitle && (
        <span className="hidden truncate border-l border-white/25 pl-3 font-brand text-[10px] font-semibold uppercase tracking-[0.16em] text-sky-100 md:block">
          {subtitle}
        </span>
      )}
    </Link>
  );
}

/**
 * Standard top bar: fixed 56px height, same colour, brand left, nav/actions right.
 * Children go in the right-hand area; `center` is an optional context badge.
 */
export function SiteHeader({
  subtitle = DEFAULT_BRAND_SUBTITLE,
  brandHref = "/",
  badge,
  leading,
  children,
  sticky = true,
  maxWidth = "max-w-7xl",
}: {
  subtitle?: string;
  brandHref?: string;
  badge?: ReactNode;
  leading?: ReactNode;
  children?: ReactNode;
  sticky?: boolean;
  maxWidth?: string;
}) {
  return (
    <header
      className={`${sticky ? "sticky top-0" : ""} z-[1000] shrink-0 border-b border-[#093554] bg-[#0c4a75] font-brand text-white shadow-md`}
    >
      <div className={`mx-auto flex h-14 w-full ${maxWidth} items-center gap-3 px-4 sm:px-6`}>
        {leading}
        <Brand href={brandHref} subtitle={subtitle} />
        {badge && <span className="hidden md:inline-flex">{badge}</span>}
        <div className="ml-auto flex min-w-0 items-center gap-2">{children}</div>
      </div>
    </header>
  );
}

/**
 * Size shared by every header link and button, so labels and borders line up. 36px tall inside the
 * 56px bar (see README, frontend checks). It sets no display value, so callers add inline-flex (or a
 * responsive hidden/inline-flex pair) themselves.
 */
export const HEADER_CONTROL =
  "h-9 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-lg px-3 text-xs font-semibold transition focus:outline-none focus-visible:ring-2 focus-visible:ring-sky-300";

/** Shared pill-style nav link for headers. */
export function NavLink({
  href,
  children,
  hideBelow,
  variant = "default",
}: {
  href: string;
  children: ReactNode;
  hideBelow?: "sm" | "md" | "lg";
  variant?: "default" | "primary" | "success";
}) {
  const hide = hideBelow === "sm" ? "hidden sm:inline-flex" : hideBelow === "md" ? "hidden md:inline-flex" : hideBelow === "lg" ? "hidden lg:inline-flex" : "inline-flex";
  const tone =
    variant === "primary"
      ? "bg-red-600 hover:bg-red-500"
      : variant === "success"
        ? "bg-emerald-600 hover:bg-emerald-500"
        : "bg-white/10 hover:bg-white/20";
  return (
    <Link
      href={href}
      className={`${HEADER_CONTROL} ${hide} ${tone} text-white`}
    >
      {children}
    </Link>
  );
}
