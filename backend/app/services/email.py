"""Transactional email service (SMTP client with development simulation outbox).

Handles:
1. Account invitation emails with secure setup links.
2. Password reset emails with expiring single-use links.
3. In-memory outbox & simulation logger when SMTP is not configured (demo/dev/testing).
"""

import logging
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.parse import quote

from app.config import get_settings

logger = logging.getLogger("drch.email")

# In-memory outbox for testing and sandbox execution verification
_outbox: list[dict[str, Any]] = []


def get_outbox() -> list[dict[str, Any]]:
    """Return delivered emails from in-memory outbox (test helper)."""
    return list(_outbox)


def clear_outbox() -> None:
    """Clear in-memory outbox (test fixture helper)."""
    _outbox.clear()


def _send_raw_email(to_email: str, subject: str, text_content: str, html_content: str | None = None) -> bool:
    """
    Sends an email using configured SMTP settings, or appends to simulation outbox.
    Returns True if sent or successfully recorded in outbox, False if transport failed.
    """
    settings = get_settings()

    record = {
        "to": to_email,
        "from": settings.email_from,
        "subject": subject,
        "text": text_content,
        "html": html_content,
    }
    _outbox.append(record)

    if not settings.smtp_host:
        logger.info(
            "Simulated Email [SMTP_HOST not set]: To=%s | Subject=%s",
            to_email,
            subject,
        )
        return True

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.email_from
        msg["To"] = to_email
        msg.set_content(text_content)
        if html_content:
            msg.add_alternative(html_content, subtype="html")

        if settings.smtp_port == 465:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                if settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.ehlo()
                if server.has_extn("starttls"):
                    server.starttls()
                    server.ehlo()
                if settings.smtp_username and settings.smtp_password:
                    server.login(settings.smtp_username, settings.smtp_password)
                server.send_message(msg)

        logger.info("Email dispatched successfully: To=%s | Subject=%s", to_email, subject)
        return True
    except Exception:
        logger.exception("Failed to dispatch email via SMTP to %s", to_email)
        return False


def send_invitation_email(
    to_email: str,
    recipient_name: str,
    role_name: str,
    token: str,
) -> bool:
    """Dispatches an account invitation email containing a secure setup link."""
    settings = get_settings()
    setup_link = f"{settings.frontend_url}/setup-account?token={token}"
    hours = settings.invitation_token_hours

    subject = "Account Invitation — Gujarat Disaster Management Platform (DRCH)"
    text = (
        f"Hello {recipient_name},\n\n"
        f"You have been invited to join the Disaster Response Coordination Hub (DRCH) "
        f"for the State of Gujarat as {role_name}.\n\n"
        f"To complete your account setup and choose your password, please open the following link:\n"
        f"{setup_link}\n\n"
        f"This setup link will expire in {hours} hours.\n\n"
        f"If you did not expect this invitation, please ignore this email or contact support.\n\n"
        f"Gujarat State Disaster Management Operations"
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #b91c1c;">Gujarat Disaster Response Coordination Hub</h2>
    <p>Hello <strong>{recipient_name}</strong>,</p>
    <p>You have been invited to join the <strong>Disaster Response Coordination Hub (DRCH)</strong> as <strong>{role_name}</strong>.</p>
    <p>Please click the button below to choose your password and activate your account:</p>
    <p style="margin: 30px 0;">
        <a href="{setup_link}" style="background-color: #b91c1c; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Set Up My Account</a>
    </p>
    <p style="font-size: 0.9em; color: #666;">Or copy and paste this link in your browser:<br/><a href="{setup_link}">{setup_link}</a></p>
    <p style="font-size: 0.85em; color: #888;">This invitation link will expire in {hours} hours.<br/>For your security, never forward this email.</p>
</body>
</html>"""
    return _send_raw_email(to_email, subject, text, html)


def send_credentials_reset_email(to_email: str, recipient_name: str, role_name: str, token: str) -> bool:
    """Tell a staff member an administrator reset their sign-in, with a single-use link to set it up again."""
    settings = get_settings()
    setup_link = f"{settings.frontend_url}/setup-account?token={token}"
    hours = settings.invitation_token_hours
    subject = "Your sign-in was reset — Gujarat Disaster Management Platform (DRCH)"
    text = (
        f"Hello {recipient_name},\n\n"
        f"An administrator reset the sign-in for your {role_name} account. Your old password and authenticator "
        f"no longer work. To get back in, open this link and choose a new password and set up your authenticator "
        f"app again:\n{setup_link}\n\n"
        f"The link works once and expires in {hours} hours.\n\n"
        "If you did not expect this, contact your administrator before using the link.\n\n"
        "Gujarat State Disaster Management Operations"
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #b91c1c;">Gujarat Disaster Response Coordination Hub</h2>
    <p>Hello <strong>{recipient_name}</strong>,</p>
    <p>An administrator reset the sign-in for your <strong>{role_name}</strong> account. Your old password and authenticator no longer work.</p>
    <p style="margin: 30px 0;">
        <a href="{setup_link}" style="background-color: #b91c1c; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Set a new password</a>
    </p>
    <p style="font-size: 0.9em; color: #666;">Or copy and paste this link in your browser:<br/><a href="{setup_link}">{setup_link}</a></p>
    <p style="font-size: 0.85em; color: #888;">The link works once and expires in {hours} hours. If you did not expect this, contact your administrator before using it.</p>
</body>
</html>"""
    return _send_raw_email(to_email, subject, text, html)


def send_verification_email(to_email: str, recipient_name: str) -> bool:
    """Citizen email-verification STUB (S1-03): the link only goes to the in-memory outbox and is never emailed.

    No token is stored and verification is not enforced; accounts are ACTIVE on registration.
    With SMTP configured nothing is sent until a /verify-email page and token check exist.
    """
    settings = get_settings()
    if settings.smtp_host:
        # There is no /verify-email page yet, so a real email would send every new citizen to a dead link.
        logger.info("Email verification is not implemented yet; no verification email sent")
        return False
    link = f"{settings.frontend_url}/verify-email?email={quote(to_email)}"
    text = f"Hello {recipient_name},\n\nWelcome to ResQ. Confirm your email address: {link}\n"
    return _send_raw_email(to_email, "Confirm your ResQ account email", text)


def send_notification_email(to_email: str, recipient_name: str, title: str, body: str) -> bool:
    """Email copy of an in-app notification for a citizen who turned email alerts on.

    In-app notifications stay the source of truth; this is a convenience. With no SMTP_HOST it is only
    outboxed and logged (simulated), like the other emails.
    """
    settings = get_settings()
    text = (
        f"Hello {recipient_name},\n\n{title}\n\n{body}\n\n"
        f"See the full status in My Reports: {settings.frontend_url}/my-reports\n\n"
        "You can turn email alerts off on your account page.\n"
    )
    return _send_raw_email(to_email, title[:150], text)


def send_password_reset_email(
    to_email: str,
    recipient_name: str,
    token: str,
) -> bool:
    """Dispatches a password reset email containing a single-use token link."""
    settings = get_settings()
    reset_link = f"{settings.frontend_url}/reset-password?token={token}"
    minutes = settings.password_reset_token_minutes

    subject = "Password Reset Request — Gujarat Disaster Management Platform (DRCH)"
    text = (
        f"Hello {recipient_name},\n\n"
        f"We received a request to reset your password for the Disaster Response Coordination Hub (DRCH).\n\n"
        f"To choose a new password, open the link below:\n"
        f"{reset_link}\n\n"
        f"This link is valid for {minutes} minutes and can only be used once.\n\n"
        f"If you did not request a password reset, no action is needed. Your current password remains secure.\n\n"
        f"Gujarat State Disaster Management Operations"
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
    <h2 style="color: #b91c1c;">Gujarat Disaster Response Coordination Hub</h2>
    <p>Hello <strong>{recipient_name}</strong>,</p>
    <p>We received a request to reset your password for the <strong>Disaster Response Coordination Hub (DRCH)</strong>.</p>
    <p>Please click the button below to set a new password:</p>
    <p style="margin: 30px 0;">
        <a href="{reset_link}" style="background-color: #2563eb; color: white; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">Reset Password</a>
    </p>
    <p style="font-size: 0.9em; color: #666;">Or copy and paste this link in your browser:<br/><a href="{reset_link}">{reset_link}</a></p>
    <p style="font-size: 0.85em; color: #888;">This reset link will expire in {minutes} minutes and is single-use.<br/>If you did not request this, please disregard this email.</p>
</body>
</html>"""
    return _send_raw_email(to_email, subject, text, html)

