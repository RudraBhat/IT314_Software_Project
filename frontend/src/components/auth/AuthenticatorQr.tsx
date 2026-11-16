"use client";

import { QRCodeSVG } from "qrcode.react";

/**
 * QR code for an authenticator app. It is drawn in the browser from the otpauth URI, so the
 * secret never goes to a third-party QR service. Renders nothing for anything that is not an
 * otpauth:// URI, and the caller keeps the manual key entry as the fallback.
 */
export function AuthenticatorQr({ uri }: { uri?: string }) {
  if (!uri || !uri.startsWith("otpauth://")) return null;
  return (
    <div className="flex justify-center">
      <div className="rounded-xl bg-white p-3">
        <QRCodeSVG
          value={uri}
          size={176}
          level="M"
          marginSize={1}
          role="img"
          aria-label="QR code to add this account to your authenticator app"
        />
      </div>
    </div>
  );
}
