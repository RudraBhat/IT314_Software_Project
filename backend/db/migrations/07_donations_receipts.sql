-- DRCH - Migration 07: receipt numbers for confirmed donations (REC-YYYY-NNNNNN).
BEGIN;
CREATE SEQUENCE IF NOT EXISTS receipt_seq;
COMMIT;
