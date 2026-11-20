# Security policy

ResQ handles emergency reports, people's locations and staff accounts with operational access. Please report security problems privately so they can be fixed before anyone can misuse them.

## Supported versions

| Version | Supported |
|---|---|
| `main` (deployed to staging and production) | Yes |
| `1.0.x`, from the first release on 30 November 2026 | Yes |
| Any other branch, fork or older commit | No |

After 1.0.0, security fixes go to the latest `1.x` release and to `main`.

## Reporting a vulnerability

**Do not open a public issue, pull request or discussion for a security problem.**

Use GitHub's private reporting instead:

1. Open the repository's **Security** tab.
2. Choose **Report a vulnerability**.
3. Describe the problem, as shown below.

Only the maintainers can see the report. If the button is missing, open an issue that says only "Security report: please contact me privately". Include no details, and a maintainer will reach out.

A useful report includes:
- the affected component (`frontend/`, `backend/`, `ai-workers/`, `models/`, a workflow or a deployment), and the endpoint, page or file
- the steps to reproduce it, and what an attacker gains
- the commit, branch or version you tested
- any proof-of-concept, kept to the minimum needed to show the problem.

### What to expect

| Step | Target |
|---|---|
| Acknowledgement | within 3 working days |
| First assessment and severity | within 7 working days |
| Fix or mitigation for a critical or high issue | as soon as possible, normally within 30 days |

We will keep you updated, credit you in the release notes unless you prefer otherwise, and tell you before anything is disclosed publicly.

## Testing rules

Test only against a local copy (see [CONTRIBUTING.md](CONTRIBUTING.md#local-development)) or with accounts you created yourself. Please do not:
- access, change or delete data that is not yours, including real incident reports, reporter details or audit logs
- run denial-of-service, load or spam tests against the hosted services
- use social engineering, phishing or physical attacks against maintainers or users
- send real emergency reports or SOS alerts as part of a test.

Real emergencies must always go to 112. ResQ does not replace the emergency services.

## In scope

- Authentication and sessions: password sign-in, Google sign-in, TOTP multi-factor sign-in, account lockout, session and token revocation.
- Authorisation: role and permission checks between citizens, Disaster Management staff, field teams and administrators, and access to another user's data.
- Exposure of reporter personal data or precise locations through public endpoints or the public map.
- The append-only, hash-chained audit log.
- Injection (SQL, command, template), cross-site scripting, cross-site request forgery and server-side request forgery.
- Prompt injection that makes an AI service change an incident, priority or dispatch. AI output must stay advisory.
- The sandbox donation flow's signature checks.
- Secrets or credentials committed to the repository, and weaknesses in CI/CD workflows.

## Out of scope

- Reports that only list a dependency version, without showing the vulnerable code can be reached in ResQ.
- Missing best-practice headers or settings with no demonstrated impact.
- Problems that need a compromised device, browser or administrator account.
- Rate limits or availability of free-tier hosting (Render cold starts).
- Data clearly labelled as simulated, sample or sandbox.

## How we handle security in the project

- Every pull request runs a secrets scan (Gitleaks), static analysis (Bandit, CodeQL), dependency audits (`pip-audit`, `npm audit`) and container image scans (Trivy). See [`.github/workflows/`](.github/workflows/).
- Passwords are hashed with Argon2id. Staff accounts require TOTP. Every state change is written to a tamper-evident audit log.
- Secrets live only in the hosting providers and GitHub environment secrets, never in the repository. [docs/architecture/env-variables.md](docs/architecture/env-variables.md) lists names only.
- The latest internal review is in [docs/quality/security-review.md](docs/quality/security-review.md).
