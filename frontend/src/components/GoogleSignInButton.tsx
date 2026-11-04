"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { backendGoogleLogin } from "../services/authApi";

declare global {
  interface Window {
    google?: any;
  }
}

interface GoogleSignInButtonProps {
  mode?: "login" | "signup";
  onSuccess?: () => void;
  onError?: (err: string) => void;
  next?: string;
}

export function GoogleSignInButton({
  mode = "login",
  onSuccess,
  onError,
  next,
}: GoogleSignInButtonProps) {
  const router = useRouter();
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const [googleLoading, setGoogleLoading] = useState(false);

  useEffect(() => {
    const clientId = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID;
    if (!clientId) return;

    const scriptId = "google-jssdk";
    const initGoogle = () => {
      if (!window.google?.accounts?.id || !googleBtnRef.current) return;
      try {
        window.google.accounts.id.initialize({
          client_id: clientId,
          callback: async (response: any) => {
            if (!response?.credential) return;
            setGoogleLoading(true);
            try {
              const res = await backendGoogleLogin(response.credential);
              if (res.success && res.user) {
                router.refresh();
                if (onSuccess) {
                  onSuccess();
                } else if (next && next.startsWith("/") && !next.startsWith("//")) {
                  router.push(next);
                } else {
                  router.push("/");
                }
              } else if (res.mfa_required) {
                onError?.(
                  res.message || "MFA required for privileged account. Please enter your TOTP code."
                );
              } else {
                onError?.(res.error || "Google authentication failed.");
              }
            } catch {
              onError?.("Failed to connect to authentication server.");
            } finally {
              setGoogleLoading(false);
            }
          },
        });

        googleBtnRef.current.innerHTML = "";
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: "filled_blue",
          size: "large",
          width: 320,
          text: mode === "signup" ? "signup_with" : "continue_with",
          shape: "pill",
        });
      } catch (err) {
        console.warn("Google Sign-In initialization failed", err);
      }
    };

    if (window.google?.accounts?.id) {
      initGoogle();
    } else {
      let script = document.getElementById(scriptId) as HTMLScriptElement;
      if (!script) {
        script = document.createElement("script");
        script.id = scriptId;
        script.src = "https://accounts.google.com/gsi/client";
        script.async = true;
        script.defer = true;
        script.onload = () => setTimeout(initGoogle, 100);
        document.body.appendChild(script);
      } else {
        script.addEventListener("load", () => setTimeout(initGoogle, 100));
      }
    }
  }, [mode, next, onSuccess, onError]);

  return (
    <div className="w-full flex flex-col items-center">
      <div className="relative my-3.5 w-full">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-slate-700/80"></div>
        </div>
        <div className="relative flex justify-center text-xs">
          <span className="bg-[#0b1222] px-3 text-slate-400 font-medium text-[11px]">
            Or continue with
          </span>
        </div>
      </div>

      <div className="flex flex-col items-center justify-center min-h-[44px]">
        <div ref={googleBtnRef} className="flex justify-center" />
        {googleLoading && (
          <div className="text-xs text-sky-400 flex items-center gap-1.5 mt-2 animate-pulse">
            <span>⏳</span> Authenticating with Google...
          </div>
        )}
      </div>
    </div>
  );
}
