-- =====================================================================
-- DRCH - Migration 15: Refresh tokens (rotating, with session limits)
--
-- Access tokens stay short-lived. A refresh token lets a browser obtain a
-- new access token without signing in again, within two limits:
--   * idle_expires_at      slides forward each time the token is used
--   * absolute_expires_at  fixed when the session starts, never extended
-- Tokens are stored only as SHA-256 hashes and rotated on every use. A token
-- that was already rotated and is presented again outside a short grace
-- window revokes its whole family (session). Resetting a password, MFA or
-- logging out bumps user_auth.token_version, which also invalidates them.
-- =====================================================================

CREATE TABLE IF NOT EXISTS refresh_tokens (
    refresh_token_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    family_id           UUID        NOT NULL,
    token_hash          CHAR(64)    NOT NULL UNIQUE,
    token_version       INTEGER     NOT NULL,
    mfa_verified        BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    idle_expires_at     TIMESTAMPTZ NOT NULL,
    absolute_expires_at TIMESTAMPTZ NOT NULL,
    revoked_at          TIMESTAMPTZ,
    revoked_reason      TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_active
    ON refresh_tokens(user_id, family_id)
    WHERE revoked_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_family
    ON refresh_tokens(family_id);
