import os
from pathlib import Path
import psycopg
from fastapi import FastAPI
import uvicorn
if os.environ.get("ERP_MODE") != "sandbox":
    raise RuntimeError("Sandbox mode required")
url = os.environ["DATABASE_URL"]
if ".railway.internal" not in url:
    raise RuntimeError("Private database required")
with psycopg.connect(url, autocommit=True) as conn:
    for path in sorted(Path(__file__).parent.joinpath("migrations").glob("*.sql")):
        conn.execute(path.read_text())
    from selftest import run
    run(conn)
    if os.environ.get('ERP_CONTROL_SNAPSHOT'):
        from import_snapshot import import_snapshot
        count = import_snapshot(conn, os.environ['ERP_CONTROL_SNAPSHOT'], 'onedrive-control-project')
        print(f'ERP snapshot imported: {count} rows', flush=True)
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
@app.get("/health")
def health():
    with psycopg.connect(url) as conn:
        conn.execute("SELECT 1 FROM erp.projects LIMIT 1")
    return {"status":"ok","mode":"sandbox"}

@app.get("/summary")
def summary():
    with psycopg.connect(url) as conn:
        row=conn.execute("SELECT count(*),count(*) FILTER (WHERE source_rows>1),sum(reported_contract),sum(reported_uncollected_contract) FROM erp.snapshot_reconciliation").fetchone()
        verified=conn.execute("SELECT count(*),sum(balance) FROM erp.invoice_balances WHERE sent_at IS NOT NULL AND balance>0 AND currency='CAD'").fetchone()
    return {"mode":"sandbox","project_count":row[0],"duplicate_codes":row[1],"reported_contract_cad":str(row[2]) if row[2] is not None else None,"reported_uncollected_contract_cad":str(row[3]) if row[3] is not None else None,"verified_open_invoice_count":verified[0],"verified_open_invoice_cad":str(verified[1]) if verified[1] is not None else None}

if __name__ == "__main__":
    uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("PORT","8080")))
