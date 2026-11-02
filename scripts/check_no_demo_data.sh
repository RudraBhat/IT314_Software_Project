#!/usr/bin/env bash
set -euo pipefail
if git grep -nE "Kerala|Delhi|Odisha|Mumbai|Wayanad|Chandni|Paradip|admin123|provider123|user123|DEMO_USERS|resqStorage|NEXT_PUBLIC_DEMO_MODE|resq_(jwt_token|registered_users|current_user)" -- frontend/src backend/app; then
  echo "Demo or mock data found (see lines above)"; exit 1
fi
echo "OK: no demo data markers"
