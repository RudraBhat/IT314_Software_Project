"""Tests for Google OAuth 2.0 integration (Google Identity Services)."""

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import security
from app.config import get_settings
from main import app


class TestGoogleAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        # Configure demo mode & clear settings cache
        self.orig_db = os.environ.get("DATABASE_URL")
        self.orig_demo = os.environ.get("DEMO_MODE")
        self.orig_client_id = os.environ.get("GOOGLE_CLIENT_ID")

        os.environ["DEMO_MODE"] = "true"
        os.environ["GOOGLE_CLIENT_ID"] = "test-google-client-id.apps.googleusercontent.com"
        get_settings.cache_clear()

    def tearDown(self):
        if self.orig_db:
            os.environ["DATABASE_URL"] = self.orig_db
        else:
            os.environ.pop("DATABASE_URL", None)

        if self.orig_demo:
            os.environ["DEMO_MODE"] = self.orig_demo
        else:
            os.environ.pop("DEMO_MODE", None)

        if self.orig_client_id:
            os.environ["GOOGLE_CLIENT_ID"] = self.orig_client_id
        else:
            os.environ.pop("GOOGLE_CLIENT_ID", None)

        get_settings.cache_clear()

    def test_mock_google_token_authenticates_citizen(self):
        """Mock google token should authenticate as a citizen in demo mode."""
        resp = self.client.post(
            "/api/v1/auth/google",
            json={"credential": "mock-google-token:citizen.test@drch.in:Test Citizen"},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertFalse(data["mfa_required"])
        self.assertIn("access_token", data)
        self.assertEqual(data["user"]["email"], "citizen.test@drch.in")
        self.assertEqual(data["user"]["role"], "NORMAL_USER")

    @patch("app.routers.auth.httpx.AsyncClient")
    def test_google_tokeninfo_verification_audience_mismatch(self, mock_client_cls):
        """Tokens with mismatched audience must be rejected."""
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {
            "aud": "wrong-client-id.apps.googleusercontent.com",
            "email": "victim@example.com",
            "email_verified": "true",
            "sub": "12345",
        }
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = self.client.post(
            "/api/v1/auth/google",
            json={"credential": "real-looking-google-jwt-token-string"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "GOOGLE_AUTH_FAILED")

    @patch("app.routers.auth.httpx.AsyncClient")
    def test_google_tokeninfo_unverified_email_rejected(self, mock_client_cls):
        """Tokens where email_verified is false must be rejected."""
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = lambda: {
            "aud": "test-google-client-id.apps.googleusercontent.com",
            "email": "unverified@example.com",
            "email_verified": "false",
            "sub": "12345",
        }
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        resp = self.client.post(
            "/api/v1/auth/google",
            json={"credential": "real-looking-google-jwt-token-string"},
        )
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["error"]["code"], "GOOGLE_EMAIL_NOT_VERIFIED")


if __name__ == "__main__":
    unittest.main()
