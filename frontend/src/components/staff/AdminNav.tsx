"use client";

import { usePathname } from "next/navigation";

import { NavLink } from "@/components/Brand";

const LINKS = [
  { href: "/admin", label: "Accounts" },
  { href: "/admin/audit", label: "Audit log" },
  { href: "/admin/system", label: "System" },
];

/** Section links for the administration area, styled like every other header; the current page is highlighted. */
export function AdminNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Administration" className="flex items-center gap-2">
      {LINKS.map((link) => (
        <NavLink
          key={link.href}
          href={link.href}
          active={link.href === "/admin" ? pathname === "/admin" : pathname.startsWith(link.href)}
        >
          {link.label}
        </NavLink>
      ))}
    </nav>
  );
}
