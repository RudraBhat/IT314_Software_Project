// Where each role lives. Kept free of server-only imports so client components can use it too.

/**
 * Where each role lands: dispatchers in /dm, administrators in /admin, field responders in /field and
 * citizens on their dashboard. Anyone else goes to sign in.
 */
export function homeFor(role: string | null | undefined): string {
  if (role === "DISASTER_MGMT") return "/dm";
  if (role === "APP_MGMT") return "/admin";
  if (role === "FIELD_TEAM") return "/field";
  if (role === "NORMAL_USER") return "/citizen/dashboard";
  return "/login";
}
