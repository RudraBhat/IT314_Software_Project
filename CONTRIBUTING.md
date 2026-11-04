# Contributing to DRCH (Fork Workflow Guide)

Thank you for contributing to **DRCH** (Disaster Response Coordination Hub)! This document explains step-by-step how to contribute to the repository using GitHub's **Fork & Pull Request Workflow**.

Following this standard workflow ensures that your changes stay up-to-date with the main repository, avoid merge conflicts, and pass all Continuous Integration (CI) checks smoothly.

---

## Table of Contents
1. [Overview & Prerequisites](#1-overview--prerequisites)
2. [Step 1: Fork the Repository](#step-1-fork-the-repository)
3. [Step 2: Clone Your Fork Locally](#step-2-clone-your-fork-locally)
4. [Step 3: Configure Upstream Remote](#step-3-configure-upstream-remote)
5. [Step 4: Create a Dedicated Feature Branch](#step-4-create-a-dedicated-feature-branch)
6. [Step 5: Make Changes & Test Locally](#step-5-make-changes--test-locally)
7. [Step 6: Keep Your Branch In Sync with Upstream](#step-6-keep-your-branch-in-sync-with-upstream)
8. [Step 7: Commit & Push to Your Fork](#step-7-commit--push-to-your-fork)
9. [Step 8: Open a Pull Request (PR)](#step-8-open-a-pull-request-pr)
10. [Step 9: PR Review & CI Checks](#step-9-pr-review--ci-checks)
11. [Troubleshooting Common Issues](#troubleshooting-common-issues)

---

## 1. Overview & Prerequisites

- **Upstream Repository**: The official central repository (`https://github.com/Siddhcreator-1706/IT314_Software_Project.git`)
- **Origin Repository**: Your personal GitHub fork (`https://github.com/<your-username>/IT314_Software_Project.git`)
- **Git & GitHub CLI / SSH Keys**: Ensure Git is installed and you are authenticated with GitHub.

---

## Step 1: Fork the Repository

1. In the top-right corner of the page, click the **Fork** button to fork the repository.
2. Select your GitHub personal account or designated organization as the destination.
3. Ensure **"Copy the `main` branch only"** is **unchecked** if you need other branches, or checked if you only need the latest stable `main`. Click **Create fork**.

---

## Step 2: Clone Your Fork Locally

Clone your newly created fork to your local machine (replace `<your-username>` with your GitHub username):

```bash
# Using HTTPS:
git clone https://github.com/<your-username>/IT314_Software_Project.git

# Or using SSH:
git clone git@github.com:<your-username>/IT314_Software_Project.git

cd IT314_Software_Project
```

---

## Step 3: Configure Upstream Remote

Connecting your local repository to the original upstream repository allows you to pull the latest changes, preventing merge conflicts.

1. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/Siddhcreator-1706/IT314_Software_Project.git
   ```

2. Verify that both `origin` (your fork) and `upstream` (the main repo) are configured:
   ```bash
   git remote -v
   ```
   *Expected output:*
   ```text
   origin    https://github.com/<your-username>/IT314_Software_Project.git (fetch)
   origin    https://github.com/<your-username>/IT314_Software_Project.git (push)
   upstream  https://github.com/Siddhcreator-1706/IT314_Software_Project.git (fetch)
   upstream  https://github.com/Siddhcreator-1706/IT314_Software_Project.git (push)
   ```

---

## Step 4: Create a Dedicated Feature Branch

> [!IMPORTANT]
> **Never commit directly to your `main` branch.** Always create a separate, descriptive branch for each feature or bugfix.

1. Fetch the latest changes from `upstream/main`:
   ```bash
   git fetch upstream
   git checkout main
   git merge upstream/main
   ```

2. Create and switch to a new branch:
   ```bash
   # Branch naming convention: feat/<topic>, fix/<topic>, or chore/<topic>
   git checkout -b feat/citizen-report-geocoding
   ```

---

## Step 5: Make Changes & Test Locally

Before submitting code, verify that your changes build and pass linting checks locally.

### Frontend (`frontend/`):
```bash
cd frontend
npm ci --legacy-peer-deps

# 1. Run ESLint (must have 0 errors)
npm run lint

# 2. Run TypeScript & Next.js production build check
npm run build
```

### Backend (`backend/`):
```bash
cd backend
# With your virtual environment activated:
pip install -r requirements.txt
pip install ruff bandit pytest httpx

# 1. Lint and format checks
ruff check .

# 2. Security scan
bandit -r app -ll

# 3. Test suite
pytest tests/ -v
```

---

## Step 6: Keep Your Branch In Sync with Upstream

Before pushing your changes, sync with any newly merged work on `upstream/main` to avoid merge conflicts:

```bash
# Fetch latest commits from upstream
git fetch upstream

# Rebase your feature branch on upstream/main (recommended):
git rebase upstream/main

# Or merge upstream/main into your branch:
git merge upstream/main
```

If any conflicts arise, Git will prompt you to resolve them. Once resolved, continue with:
```bash
git add <resolved-files>
git rebase --continue
```

---

## Step 7: Commit & Push to Your Fork

Follow conventional commit messages (e.g., `feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`):

```bash
git add .
git commit -m "feat(citizen): add offline support for emergency reports"
```

Push the branch to **your fork** (`origin`):
```bash
git push -u origin feat/citizen-report-geocoding
```

---

## Step 8: Open a Pull Request (PR)

1. Open your fork on GitHub in your browser (`https://github.com/<your-username>/IT314_Software_Project`).
2. GitHub will automatically display a banner: **"Compare & pull request"**. Click it.
3. Configure the PR details:
   - **Base repository**: `Siddhcreator-1706/IT314_Software_Project`
   - **Base branch**: `main` *(or the designated feature integration branch)*
   - **Head repository**: `<your-username>/IT314_Software_Project`
   - **Compare branch**: `feat/citizen-report-geocoding`
4. Fill in the PR description:
   - What changes were made and why.
   - Any issue numbers linked (e.g., `Fixes #12`).
   - Screenshots or verification steps if UI changes were made.
5. Click **Create Pull Request**.

---

## Step 9: PR Review & CI Checks

Once the PR is opened:
1. **Automated CI Checks**: GitHub Actions will automatically trigger:
   - Frontend static analysis & Next.js Turbopack build
   - Python code quality, Ruff linting, & Bandit SAST security scans
   - Database schema migrations validation (PostGIS)
   - Backend unit tests & API verification
   - Container image build and Trivy vulnerability scan
2. **Review & Revisions**:
   - Repository maintainers will review the PR.
   - If updates are requested, simply make the edits locally on your branch, commit, and push to your fork (`git push origin feat/citizen-report-geocoding`). The PR and CI will update automatically.
3. **Merge**: Once approved and all checks are green, the maintainers will merge your PR into `main`.

---

## Troubleshooting Common Issues

### 1. `fatal: unable to access ... SSL certificate problem` (Windows)
If you are behind a university/office proxy or firewall:
```powershell
git config --global http.sslBackend schannel
```

### 2. "This branch has conflicts that must be resolved" on GitHub
Sync your branch with upstream:
```bash
git fetch upstream
git checkout feat/your-branch-name
git merge upstream/main
# Fix conflict markers (<<<<<<<, =======, >>>>>>>)
git add <conflicted-files>
git commit -m "chore: resolve merge conflicts with upstream main"
git push origin feat/your-branch-name
```

### 3. CI Checks are Not Triggering on Fork PRs
- First-time contributors submitting from a fork require a repository maintainer to click **"Approve and run"** on the GitHub Actions tab for security reasons.
- Ensure your PR is targetting `main` and has no merge conflicts.

---

### Happy Coding! 🚀
If you have any questions or run into hurdles, feel free to open a GitHub Issue or reach out to the project maintainers.
