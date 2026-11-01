"""Bootstrap tool for Disaster Management staff accounts.

Account administration belongs to Application Management (AM-FR-02). Until that
console exists, this command lets an operator with database access provision
staff without any hardcoded credentials:

    python -m app.cli create-staff --email ops@example.org --name "Asha Rao" \
        --permissions DISPATCH,CLOSURE,PUBLISHER,MODERATOR,SUPERVISOR
    python -m app.cli set-permissions --email ops@example.org --permissions DISPATCH
    python -m app.cli reset-mfa --email ops@example.org

The password is read interactively (or from DRCH_STAFF_PASSWORD for automation)
and never printed. The TOTP secret is shown once for enrolment in an
authenticator app and stored encrypted.
"""

import argparse
import getpass
import os
import sys

from app import audit, db, security
from app.auth import DM_ROLE, PERMISSIONS

MIN_PASSWORD_LENGTH = 12


def _parse_permissions(raw: str) -> list[str]:
    perms = sorted({p.strip().upper() for p in raw.split(",") if p.strip()})
    unknown = [p for p in perms if p not in PERMISSIONS]
    if unknown:
        sys.exit(f"Unknown permission(s): {', '.join(unknown)}. Allowed: {', '.join(PERMISSIONS)}")
    return perms


def _read_password() -> str:
    password = os.getenv("DRCH_STAFF_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match")
    if len(password) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
    return password


def _enrol_mfa(conn, user_id, email: str) -> None:
    secret = security.new_totp_secret()
    conn.execute(
        "UPDATE user_auth SET mfa_enabled = TRUE, mfa_secret = %s, token_version = token_version + 1 WHERE user_id = %s",
        (security.encrypt_mfa_secret(secret), user_id),
    )
    print("\nAdd this account to an authenticator app (shown once):")
    print(f"  Secret key : {secret}")
    print(f"  otpauth URI: {security.provisioning_uri(secret, email)}\n")


def _set_permissions(conn, user_id, perms: list[str]) -> None:
    conn.execute("DELETE FROM staff_permissions WHERE user_id = %s", (user_id,))
    for perm in perms:
        conn.execute(
            "INSERT INTO staff_permissions (user_id, permission) VALUES (%s, %s)",
            (user_id, perm),
        )


def _find_staff(conn, email: str):
    row = conn.execute(
        "SELECT u.user_id, r.code AS role FROM users u JOIN roles r USING (role_id) WHERE u.email = %s",
        (email,),
    ).fetchone()
    if row is None:
        sys.exit(f"No account with email {email}")
    if row["role"] != DM_ROLE:
        sys.exit("This tool only manages Disaster Management staff accounts")
    return row["user_id"]


def create_staff(args) -> None:
    perms = _parse_permissions(args.permissions or "")
    password_hash = security.hash_password(_read_password())
    with db.transaction() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = %s", (args.email,)).fetchone():
            sys.exit(f"An account with email {args.email} already exists")
        user_id = conn.execute(
            """
            INSERT INTO users (role_id, email, full_name, phone, designation, status)
            SELECT role_id, %s, %s, %s, %s, 'ACTIVE' FROM roles WHERE code = %s
            RETURNING user_id
            """,
            (args.email, args.name, args.phone, args.designation, DM_ROLE),
        ).fetchone()["user_id"]
        conn.execute(
            "INSERT INTO user_auth (user_id, password_hash) VALUES (%s, %s)",
            (user_id, password_hash),
        )
        _set_permissions(conn, user_id, perms)
        _enrol_mfa(conn, user_id, args.email)
        audit.record(
            conn,
            actor=None,
            action="STAFF_PROVISIONED",
            entity_type="user",
            entity_id=user_id,
            rationale="Provisioned with app.cli",
            after={"role": DM_ROLE, "permissions": perms},
        )
    print(f"Created Disaster Management account {args.email} with permissions: {', '.join(perms) or 'none'}")


def set_permissions(args) -> None:
    perms = _parse_permissions(args.permissions)
    with db.transaction() as conn:
        user_id = _find_staff(conn, args.email)
        _set_permissions(conn, user_id, perms)
        audit.record(
            conn,
            actor=None,
            action="PERMISSIONS_SET",
            entity_type="user",
            entity_id=user_id,
            rationale="Changed with app.cli",
            after={"permissions": perms},
        )
    print(f"Permissions for {args.email}: {', '.join(perms) or 'none'}")


def reset_mfa(args) -> None:
    with db.transaction() as conn:
        user_id = _find_staff(conn, args.email)
        _enrol_mfa(conn, user_id, args.email)
        audit.record(
            conn,
            actor=None,
            action="MFA_RESET",
            entity_type="user",
            entity_id=user_id,
            rationale="Reset with app.cli; existing sessions revoked",
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-staff", help="Create a Disaster Management staff account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--phone")
    create.add_argument("--designation")
    create.add_argument("--permissions", help=f"Comma-separated: {','.join(PERMISSIONS)}")
    create.set_defaults(func=create_staff)

    perms = sub.add_parser("set-permissions", help="Replace a staff member's permissions")
    perms.add_argument("--email", required=True)
    perms.add_argument("--permissions", required=True)
    perms.set_defaults(func=set_permissions)

    mfa = sub.add_parser("reset-mfa", help="Issue a new TOTP secret and revoke sessions")
    mfa.add_argument("--email", required=True)
    mfa.set_defaults(func=reset_mfa)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
