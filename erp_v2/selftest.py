def run(conn):
    from decimal import Decimal
    from uuid import uuid4
    from psycopg import errors
    k = "TEST-" + uuid4().hex
    with conn.transaction(force_rollback=True):
        p = conn.execute("INSERT INTO erp.projects(code,title) VALUES (%s,'Synthetic test') RETURNING id",(k,)).fetchone()[0]
        q = conn.execute("INSERT INTO erp.projects(code,title) VALUES (%s,'Other test') RETURNING id",(k+"-2",)).fetchone()[0]
        i = conn.execute("INSERT INTO erp.invoices(project_id,source_key,invoice_number,net_amount,tax_amount) VALUES (%s,%s,%s,100,15) RETURNING id",(p,k,k)).fetchone()[0]
        def payment(project, suffix, amount):
            return conn.execute("INSERT INTO erp.payments(project_id,source_key,amount) VALUES (%s,%s,%s) RETURNING id",(project,k+suffix,amount)).fetchone()[0]
        a=payment(p,"a",50)
        b=payment(p,"b",65)
        c=payment(q,"c",10)
        d=payment(p,"d",10)
        def allocate(payment_id, amount):
            conn.execute("INSERT INTO erp.allocations VALUES (%s,%s,%s)",(payment_id,i,amount))
        def balance():
            return conn.execute("SELECT balance FROM erp.invoice_balances WHERE id=%s",(i,)).fetchone()[0]
        def reject(payment_id, amount):
            try:
                with conn.transaction():
                    allocate(payment_id,amount)
            except errors.RaiseException:
                return
            raise RuntimeError("Invalid allocation accepted")
        assert balance()==Decimal("115")
        reject(c,10)
        reject(a,51)
        allocate(a,50)
        assert balance()==Decimal("65")
        allocate(b,65)
        assert balance()==0
        reject(d,1)
    print("ERP synthetic financial tests passed; transaction rolled back",flush=True)
