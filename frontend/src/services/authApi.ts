import { UserProfile } from "../types/resq";

export function getApiBaseUrl(): string {
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:8000`;
  }
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

const API_BASE_URL = getApiBaseUrl();

export interface AuthApiResponse {
  success: boolean;
  message?: string;
  token?: string;
  user?: UserProfile;
  error?: string;
  isOffline?: boolean;
}

/**
 * Checks whether the DRCH FastAPI Gateway is reachable.
 */
export async function checkBackendHealth(): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 1200);
    const res = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return res.ok;
  } catch {
    return false;
  }
}

/**
 * Login via Backend FastAPI Gateway.
 * If backend is offline, returns { success: false, isOffline: true }
 * allowing caller to gracefully fall back to local storage without user interruption.
 */
export async function backendLogin(
  identifier: string,
  password?: string,
  extraProfile?: Partial<UserProfile>
): Promise<AuthApiResponse> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3500);

    const email = identifier.trim().toLowerCase();
    const payload = {
      email,
      identifier,
      password: password || "",
      ...(extraProfile?.role ? { role: extraProfile.role } : {}),
      ...(extraProfile?.name ? { name: extraProfile.name } : {}),
      ...(extraProfile?.agency ? { agency: extraProfile.agency } : {}),
    };

    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      // Fallback if backend is running with alternative prefix
      if (res.status === 404) {
        res = await fetch(`${API_BASE_URL}/api/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      }
      if (res.status === 404) {
        res = await fetch(`${API_BASE_URL}/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      }
    } finally {
      clearTimeout(timeout);
    }

    const data = await res.json();
    if (!res.ok) {
      return {
        success: false,
        error: data.error?.message || data.detail || "Authentication failed on backend.",
      };
    }

    if (data.mfa_required) {
      return {
        success: false,
        error: "This staff account requires multi-factor authentication. Please use the Administrator tab.",
      };
    }

    const token = data.access_token || data.token;
    if (token && typeof window !== "undefined") {
      localStorage.setItem("resq_jwt_token", token);
    }

    const rawRole = data.role || data.user?.role || "NORMAL_USER";
    const mappedRole =
      rawRole === "DISASTER_MGMT"
        ? "Command Officer / Incident Commander"
        : rawRole === "APP_MGMT"
        ? "System Administrator"
        : extraProfile?.role || "Public / Citizen";

    const user: UserProfile = {
      id: data.user?.id || (data.user_id ? String(data.user_id) : `user_${Date.now()}`),
      name: data.user?.name || data.full_name || extraProfile?.name || email.split("@")[0],
      email: data.user?.email || data.email || email,
      phone: extraProfile?.phone || "",
      role: mappedRole,
      agency: extraProfile?.agency || (mappedRole === "Public / Citizen" ? "Public Resident" : "Disaster Response Coordination Hub"),
      badgeNumber: extraProfile?.badgeNumber,
    };

    return {
      success: true,
      token,
      user,
      message: data.message,
    };
  } catch {
    // Network or server unreachable - signal offline fallback
    return {
      success: false,
      isOffline: true,
      error: "Backend gateway unreachable",
    };
  }
}

/**
 * Signup via Backend FastAPI Gateway.
 */
export async function backendSignup(
  userData: Omit<UserProfile, "id"> & { password?: string }
): Promise<AuthApiResponse> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3500);

    const email = userData.email.trim().toLowerCase();
    const payload = {
      email,
      password: userData.password || "",
      full_name: userData.name.trim(),
      phone: userData.phone ? userData.phone.trim() : null,
      role: userData.role,
      agency: userData.agency,
      badgeNumber: userData.badgeNumber,
    };

    let res: Response;
    try {
      res = await fetch(`${API_BASE_URL}/api/v1/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (res.status === 404) {
        res = await fetch(`${API_BASE_URL}/api/v1/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      }
      if (res.status === 404) {
        res = await fetch(`${API_BASE_URL}/api/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
      }
    } finally {
      clearTimeout(timeout);
    }

    const data = await res.json();
    if (!res.ok) {
      return {
        success: false,
        error: data.error?.message || data.detail || "Registration failed on backend.",
      };
    }

    const token = data.access_token || data.token;
    if (token && typeof window !== "undefined" && process.env.NEXT_PUBLIC_DEMO_MODE === "true") {
      localStorage.setItem("resq_jwt_token", token);
    }

    const user: UserProfile = {
      id: data.user?.id || (data.user_id ? String(data.user_id) : `user_${Date.now()}`),
      name: data.user?.name || userData.name,
      email: data.user?.email || email,
      phone: userData.phone || "",
      role: userData.role || "Public / Citizen",
      agency: userData.agency || "Public Resident / Citizen",
      badgeNumber: userData.badgeNumber,
    };

    return {
      success: true,
      token,
      user,
      message: data.message,
    };
  } catch {
    return {
      success: false,
      isOffline: true,
      error: "Backend gateway unreachable",
    };
  }
}

/**
 * Sign in or Register using Google OAuth 2.0 (Google Identity Services credential).
 */
export async function backendGoogleLogin(
  credential: string
): Promise<AuthApiResponse & { mfa_required?: boolean; mfa_token?: string }> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    let res: Response;
    const baseUrl = getApiBaseUrl();
    try {
      res = await fetch(`${baseUrl}/api/v1/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential }),
        signal: controller.signal,
      });
    } finally {
      clearTimeout(timeout);
    }

    const data = await res.json();
    if (!res.ok) {
      return {
        success: false,
        error: data.error?.message || data.detail || "Google authentication failed.",
      };
    }

    if (data.mfa_required) {
      return {
        success: false,
        mfa_required: true,
        mfa_token: data.mfa_token,
        message: data.message || "Multi-factor authentication required for privileged account.",
      };
    }

    const token = data.access_token || data.token;
    if (token && typeof window !== "undefined") {
      localStorage.setItem("resq_jwt_token", token);
    }

    const roleName =
      data.user?.role === "NORMAL_USER"
        ? "Public / Citizen"
        : data.user?.role || "Public / Citizen";

    const user: UserProfile = {
      id: data.user?.id || `user_${Date.now()}`,
      name: data.user?.name || "Citizen",
      email: data.user?.email || "",
      phone: data.user?.phone || "",
      role: roleName as any,
      agency: data.user?.role === "NORMAL_USER" ? "Public Resident / Citizen" : "Disaster Response Staff",
    };

    return {
      success: true,
      token,
      user,
      message: data.message,
    };
  } catch (err: any) {
    console.error("Google Auth Request Error:", err);
    const msg =
      err?.name === "AbortError"
        ? "Google authentication request timed out."
        : err?.message
        ? `Backend connection error: ${err.message}`
        : "Backend authentication gateway unreachable.";
    return {
      success: false,
      isOffline: true,
      error: msg,
    };
  }
}
