BEGIN;
CREATE TABLE IF NOT EXISTS erp.project_snapshots (
 source_id text NOT NULL, source_row integer NOT NULL, project_code text NOT NULL,
 project_title text NOT NULL, contract_net numeric(14,2),
 physical_fraction numeric CHECK(physical_fraction BETWEEN 0 AND 1),
 received_fraction numeric CHECK(received_fraction BETWEEN 0 AND 1),
 source_status text, imported_at timestamptz NOT NULL DEFAULT now(),
 PRIMARY KEY(source_id,source_row)
);
CREATE OR REPLACE VIEW erp.snapshot_reconciliation AS
SELECT project_code,count(*) AS source_rows,
CASE WHEN count(*)=1 THEN max(contract_net) END AS reported_contract,
CASE WHEN count(*)=1 THEN max(contract_net*(1-received_fraction)) END AS reported_uncollected_contract
FROM erp.project_snapshots GROUP BY project_code;
COMMIT;
