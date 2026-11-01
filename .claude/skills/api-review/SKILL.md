---
name: api-review
description: Review REST API endpoint contracts, schemas, headers, status codes, and error formatting.
---

# API Review Workflow (/api-review)

Review REST endpoints against DRCH API design standards and SRS specifications:

## 1. Review Checklist
- **Path Standards:** Check that all operational and dispatch routes reside under `/api/v1/`.
- **Error Formatting:** Confirm that non-2xx responses strictly conform to SRS s.15.7:
  ```json
  {
    "error": {
      "code": "STRING_ERROR_CODE",
      "message": "Human readable explanation",
      "details": null
    }
  }
  ```
- **Idempotency:** Verify sensitive write operations support `Idempotency-Key` headers where appropriate.
- **Status Codes:** Ensure correct HTTP semantics (`201` for creation, `204` for no-content mutations, `409` for resource conflicts, `422` for validation errors).
- **Documentation Parity:** Verify new or modified routes match `docs/api_contracts.md`.

## 2. Output
Provide endpoint path, HTTP method, schema validation status, and contract consistency score.

