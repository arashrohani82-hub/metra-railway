BEGIN;
CREATE TABLE IF NOT EXISTS erp.receipt_snapshots (
 source_key text PRIMARY KEY, invoice_number text, invoice_filename text,
 invoice_total numeric(14,2), amount numeric(14,2) NOT NULL CHECK(amount>0),
 received_on date NOT NULL, accounting_only boolean NOT NULL DEFAULT false
);
CREATE OR REPLACE VIEW erp.receipt_reconciliation AS
SELECT invoice_number,count(*) AS receipt_count,sum(amount) AS received,
CASE WHEN count(DISTINCT invoice_total)=1 THEN max(invoice_total) END AS source_invoice_total,
CASE WHEN count(DISTINCT invoice_total)=1 THEN max(invoice_total)-sum(amount) END AS source_balance
FROM erp.receipt_snapshots WHERE invoice_number IS NOT NULL AND NOT accounting_only GROUP BY invoice_number;
COMMIT;
