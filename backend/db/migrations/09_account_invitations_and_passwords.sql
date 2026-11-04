-- =====================================================================
-- DRCH - Migration 05: Secure Email Invitations & Password Management
--
-- Enables:
--   1. PENDING_SETUP state in account_status enum
--   2. Nullable password_hash in user_auth for invited accounts
--   3. Secure invitation token hash (SHA-256) and expiration timestamp
--   4. Invited-by user tracking
--   5. Fast B-Tree indexes on token hashes
-- =====================================================================

-- 1. Extend account_status enum with PENDING_SETUP
ALTER TYPE account_status ADD VALUE IF NOT EXISTS 'PENDING_SETUP';

-- 2. Make user_auth.password_hash nullable so invited accounts can be created prior to password choice
ALTER TABLE user_auth ALTER COLUMN password_hash DROP NOT NULL;

-- 3. Add invitation token hash, expiration, and inviter tracking
ALTER TABLE user_auth
    ADD COLUMN IF NOT EXISTS invitation_token_hash CHAR(64),
    ADD COLUMN IF NOT EXISTS invitation_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS invited_by UUID REFERENCES users(user_id) ON DELETE SET NULL;

-- 4. B-Tree indexes for fast hash lookups
CREATE INDEX IF NOT EXISTS idx_user_auth_invitation_hash 
    ON user_auth(invitation_token_hash) 
    WHERE invitation_token_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_user_auth_reset_hash 
    ON user_auth(password_reset_token_hash) 
    WHERE password_reset_token_hash IS NOT NULL;

