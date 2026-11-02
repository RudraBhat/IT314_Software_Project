---
trigger: model_decision
description: Load when creating or modifying frontend pages, React components, hooks, styling, routing, or API integration.
---

# Frontend Engineering Rules

- **Framework & Directory Structure:**
  - Built with **Next.js 14+ (App Router)**, React 19, TypeScript, and Tailwind CSS.
  - Page routes live in `frontend/src/app/`; reusable components in `frontend/src/components/`.
- **Reusable Component First:**
  - Inspect `frontend/src/components/ui.tsx` for core UI primitives (Button, Card, Input, Modal, Badge).
  - Inspect `frontend/src/components/badges.tsx` for status and severity indicators.
  - Inspect `frontend/src/components/dm/LiveOperationsLayer.tsx` for Leaflet GIS maps.
- **State Management & Context:**
  - Consume global operational state, active user identity, and notifications via `ResQContext` (`frontend/src/context/ResQContext.tsx`).
- **API Integration & Security:**
  - Route all backend API requests through Next.js proxy handlers (`frontend/src/app/api/`) or the unified client wrapper in `frontend/src/lib/api.ts`.
  - Never hardcode backend URLs, API keys, or JWT secrets in client-side bundles.
  - Never store plain authentication tokens in unencrypted local storage if session cookies are configured.
- **Resilience & UX States:**
  - Explicitly handle and test all UI states: `loading`, `error`, `empty`, and `success`.
  - Maintain mobile responsiveness and high-contrast accessibility across all tactical dashboards.
- **Zero Duplicate Packages:**
  - Check `frontend/package.json` before proposing any new dependency.
