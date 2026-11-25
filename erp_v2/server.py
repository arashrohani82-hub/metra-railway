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
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
@app.get("/health")
def health():
    with psycopg.connect(url) as conn:
        conn.execute("SELECT 1 FROM erp.projects LIMIT 1")
    return {"status":"ok","mode":"sandbox"}
if __name__ == "__main__":
    uvicorn.run(app,host="0.0.0.0",port=int(os.environ.get("PORT","8080")))
