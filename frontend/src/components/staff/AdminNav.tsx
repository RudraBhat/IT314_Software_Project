"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/admin", label: "Accounts" },
  { href: "/admin/audit", label: "Audit log" },
  { href: "/admin/system", label: "System" },
];

/** Section links for the administration area; the current page is marked for screen readers too. */
export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Administration" className="flex items-center gap-1">
      {LINKS.map((link) => {
        const current = link.href === "/admin" ? pathname === "/admin" : pathname.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={current ? "page" : undefined}
            className={`rounded-full px-3 py-1.5 text-xs font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-300 ${
              current ? "bg-white/20 text-white" : "text-sky-100 hover:bg-white/10"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
