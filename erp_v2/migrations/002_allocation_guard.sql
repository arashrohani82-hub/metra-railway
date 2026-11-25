BEGIN;
CREATE OR REPLACE FUNCTION erp.validate_allocation() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p erp.payments%ROWTYPE; i erp.invoices%ROWTYPE; pa numeric; ia numeric;
BEGIN
 SELECT * INTO STRICT p FROM erp.payments WHERE id=NEW.payment_id FOR UPDATE;
 SELECT * INTO STRICT i FROM erp.invoices WHERE id=NEW.invoice_id FOR UPDATE;
 IF p.project_id<>i.project_id OR p.currency<>i.currency OR p.reversed_at IS NOT NULL OR i.voided_at IS NOT NULL THEN RAISE EXCEPTION 'Invalid allocation'; END IF;
 SELECT coalesce(sum(amount),0) INTO pa FROM erp.allocations WHERE payment_id=NEW.payment_id AND (TG_OP='INSERT' OR (payment_id,invoice_id)<>(OLD.payment_id,OLD.invoice_id));
 SELECT coalesce(sum(a.amount),0) INTO ia FROM erp.allocations a JOIN erp.payments pp ON pp.id=a.payment_id WHERE a.invoice_id=NEW.invoice_id AND pp.reversed_at IS NULL AND (TG_OP='INSERT' OR (a.payment_id,a.invoice_id)<>(OLD.payment_id,OLD.invoice_id));
 IF pa+NEW.amount>p.amount OR ia+NEW.amount>i.net_amount+i.tax_amount THEN RAISE EXCEPTION 'Allocation exceeds balance'; END IF;
 RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS allocation_guard ON erp.allocations;
CREATE TRIGGER allocation_guard BEFORE INSERT OR UPDATE ON erp.allocations FOR EACH ROW EXECUTE FUNCTION erp.validate_allocation();
COMMIT;
