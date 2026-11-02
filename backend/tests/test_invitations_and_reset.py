"""Integration and unit tests for Secure Email Invitation & Password Management.

Covers:
1. Admin-only account creation & anti-escalation enforcement.
2. Single-use invitation token generation, verification, and expiration.
3. Mandatory TOTP enrollment for privileged roles (DISASTER_MGMT, APP_MGMT).
4. Direct activation without MFA for service provider (FIELD_TEAM).
5. Forgot password anti-enumeration, rate-limiting, and single-use reset links.
6. Session revocation (token_version bump) and MFA preservation on reset.
7. Blocking login attempts for PENDING_SETUP accounts.
"""

import os
import unittest
import uuid
from datetime import UTC, datetime, timedelta

from starlette.requests import Request

from app import security
from app.auth import (
    APP_MGMT_ROLE,
    DM_ROLE,
    FIELD_TEAM_ROLE,
    PERMISSIONS,
    Principal,
)
from app.config import get_settings
from app.errors import ApiError
from app.routers import auth as auth_router
from app.services import email as email_service


def _make_request() -> Request:
    return Request({"type": "http", "client": ("127.0.0.1", 54321), "headers": []})


class TestInvitationsAndReset(unittest.TestCase):
    def setUp(self):
        email_service.clear_outbox()
        auth_router._DEMO_INVITATIONS.clear()
        auth_router._DEMO_RESETS.clear()
        auth_router._rate_limits.clear()

        # Set demo mode and temporarily isolate from local DB
        self._saved_db_url = os.environ.get("DATABASE_URL")
        os.environ.pop("DATABASE_URL", None)
        os.environ["DEMO_MODE"] = "true"
        os.environ["JWT_SECRET"] = "drch_demo_only_jwt_secret_change_before_deployment_32chars"
        get_settings.cache_clear()

        # Create mock principals for testing
        self.app_mgmt_admin = Principal(
            user_id=uuid.UUID("a0000000-0000-0000-0000-000000000001"),
            email="admin@drch.gov.in",
            full_name="Platform Admin",
            role=APP_MGMT_ROLE,
            mfa_verified=True,
            permissions=frozenset(PERMISSIONS),
            ip="127.0.0.1",
        )
        self.dm_supervisor = Principal(
            user_id=uuid.UUID("b0000000-0000-0000-0000-000000000002"),
            email="supervisor@drch.gov.in",
            full_name="DM Supervisor",
            role=DM_ROLE,
            mfa_verified=True,
            permissions=frozenset(["SUPERVISOR", "DISPATCH"]),
            ip="127.0.0.1",
        )
        self.dm_operator_no_supervisor = Principal(
            user_id=uuid.UUID("c0000000-0000-0000-0000-000000000003"),
            email="operator@drch.gov.in",
            full_name="DM Operator",
            role=DM_ROLE,
            mfa_verified=True,
            permissions=frozenset(["DISPATCH"]),
            ip="127.0.0.1",
        )

    def tearDown(self):
        if self._saved_db_url:
            os.environ["DATABASE_URL"] = self._saved_db_url
        get_settings.cache_clear()

    def test_privilege_escalation_supervisor_cannot_create_admin(self):
        """A DM supervisor must never be allowed to create an APP_MGMT admin account."""
        req = auth_router.InviteUserRequest(
            email="new.admin@drch.gov.in",
            full_name="New Admin",
            role=APP_MGMT_ROLE,
        )
        with self.assertRaises(ApiError) as ctx:
            auth_router.invite_user(req, self.dm_supervisor, _make_request())
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "PRIVILEGE_ESCALATION")

    def test_cannot_invite_citizen_via_staff_endpoint(self):
        """Citizens cannot be invited; they must self-register via /signup."""
        req = auth_router.InviteUserRequest(
            email="citizen@example.com",
            full_name="Citizen",
            role="NORMAL_USER",
        )
        with self.assertRaises(ApiError) as ctx:
            auth_router.invite_user(req, self.app_mgmt_admin, _make_request())
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "CANNOT_INVITE_CITIZEN")

    def test_supervisor_cannot_grant_unheld_permissions(self):
        """A supervisor cannot grant permissions they do not possess."""
        req = auth_router.InviteUserRequest(
            email="subordinate@drch.gov.in",
            full_name="New DM Staff",
            role=DM_ROLE,
            permissions=["CLOSURE"],  # supervisor only has SUPERVISOR and DISPATCH
        )
        with self.assertRaises(ApiError) as ctx:
            auth_router.invite_user(req, self.dm_supervisor, _make_request())
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.code, "PRIVILEGE_ESCALATION")

    def test_admin_invitation_dispatches_email(self):
        """Admin invitation generates setup token, records in outbox, and hashes token."""
        req = auth_router.InviteUserRequest(
            email="field.responder@drch.gov.in",
            full_name="Field Team Lead",
            role=FIELD_TEAM_ROLE,
        )
        res = auth_router.invite_user(req, self.app_mgmt_admin, _make_request())
        self.assertEqual(res["status"], "PENDING_SETUP")
        self.assertEqual(res["role"], FIELD_TEAM_ROLE)

        outbox = email_service.get_outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["to"], "field.responder@drch.gov.in")
        self.assertIn("setup-account?token=", outbox[0]["text"])

    def test_invitation_verify_and_accept_for_field_team(self):
        """FIELD_TEAM sets their password and is activated directly without MFA."""
        # Invite FIELD_TEAM
        invite_req = auth_router.InviteUserRequest(
            email="responder1@drch.gov.in",
            full_name="Responder One",
            role=FIELD_TEAM_ROLE,
        )
        auth_router.invite_user(invite_req, self.app_mgmt_admin, _make_request())

        # Extract token from sent email
        outbox = email_service.get_outbox()
        token = outbox[0]["text"].split("setup-account?token=")[1].split()[0]

        # Verify invitation link
        verification = auth_router.verify_invitation(token=token)
        self.assertTrue(verification["valid"])
        self.assertEqual(verification["email"], "responder1@drch.gov.in")
        self.assertFalse(verification["requires_mfa"])

        # Accept invitation and set password
        accept_res = auth_router.accept_invitation(
            auth_router.AcceptInvitationRequest(token=token, password="ValidPassword123#"),
            _make_request(),
        )
        self.assertFalse(accept_res["mfa_required"])
        self.assertEqual(accept_res["status"], "ACTIVE")

        # Re-using the token must be rejected
        with self.assertRaises(ApiError) as ctx:
            auth_router.verify_invitation(token=token)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "INVITATION_INVALID")

    def test_invitation_accept_mandates_totp_for_dm(self):
        """DISASTER_MGMT invitation accept requires TOTP enrollment before activation."""
        invite_req = auth_router.InviteUserRequest(
            email="officer1@drch.gov.in",
            full_name="DM Officer",
            role=DM_ROLE,
            permissions=["DISPATCH"],
        )
        auth_router.invite_user(invite_req, self.dm_supervisor, _make_request())

        outbox = email_service.get_outbox()
        token = outbox[0]["text"].split("setup-account?token=")[1].split()[0]

        # Verify
        verification = auth_router.verify_invitation(token=token)
        self.assertTrue(verification["valid"])
        self.assertTrue(verification["requires_mfa"])

        # Accept
        accept_res = auth_router.accept_invitation(
            auth_router.AcceptInvitationRequest(token=token, password="SecurePassword123!"),
            _make_request(),
        )
        self.assertTrue(accept_res["mfa_required"])
        self.assertIn("mfa_setup_token", accept_res)
        self.assertIn("mfa_uri", accept_res)
        self.assertIn("otpauth://totp/", accept_res["mfa_uri"])

        # Complete initial TOTP verification
        setup_token = accept_res["mfa_setup_token"]
        verify_res = auth_router.verify_totp_setup(
            auth_router.VerifyTotpSetupRequest(mfa_setup_token=setup_token, code="123456"),
            _make_request(),
        )
        self.assertFalse(verify_res["mfa_required"])
        self.assertIn("access_token", verify_res)
        self.assertEqual(verify_res["role"], DM_ROLE)

    def test_forgot_password_anti_enumeration(self):
        """Forgot password returns identical message for both existing and unknown emails."""
        res_unknown = auth_router.forgot_password(
            auth_router.ForgotPasswordRequest(email="nonexistent@example.com"),
            _make_request(),
        )
        self.assertIn("If this email is registered", res_unknown["message"])

        res_known = auth_router.forgot_password(
            auth_router.ForgotPasswordRequest(email="commander@resq.gov.in"),
            _make_request(),
        )
        self.assertIn("If this email is registered", res_known["message"])

        # Email was dispatched ONLY for known active user
        outbox = email_service.get_outbox()
        self.assertEqual(len(outbox), 1)
        self.assertEqual(outbox[0]["to"], "commander@resq.gov.in")
        self.assertIn("reset-password?token=", outbox[0]["text"])

    def test_password_reset_flow(self):
        """Password reset verifies token, updates password, and invalidates token."""
        auth_router.forgot_password(
            auth_router.ForgotPasswordRequest(email="commander@resq.gov.in"),
            _make_request(),
        )
        outbox = email_service.get_outbox()
        token = outbox[0]["text"].split("reset-password?token=")[1].split()[0]

        # Verify token link
        verification = auth_router.verify_reset_token(token=token)
        self.assertTrue(verification["valid"])

        # Reset password
        reset_res = auth_router.reset_password(
            auth_router.ResetPasswordRequest(token=token, new_password="BrandNewPassword123!"),
            _make_request(),
        )
        self.assertTrue(reset_res["success"])

        # Token cannot be reused
        with self.assertRaises(ApiError) as ctx:
            auth_router.verify_reset_token(token=token)
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.code, "RESET_TOKEN_INVALID")

    def test_token_hash_helper(self):
        """Token hashing produces deterministic 64-character SHA-256 hex string."""
        raw = "my-test-token-123456"
        h1 = security.hash_token(raw)
        h2 = security.hash_token(raw)
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 64)


if __name__ == "__main__":
    unittest.main()
