import csv
import io
import re
from decimal import Decimal, InvalidOperation
def parse_control(text):
    sections=[s for s in text.split("\f") if "Project No" in s.splitlines()[0] and "Financial % Complet" in s.splitlines()[0]]
    if len(sections)!=1: raise ValueError("Expected exactly one Control Project table")
    def number(v, fraction=False):
        if not v.strip(): return None
        n=Decimal(v.strip())
        if not n.is_finite() or n<0 or (fraction and n>1): raise ValueError("Invalid numeric value")
        return n
    rows=[]
    for r in csv.DictReader(io.StringIO(sections[0])):
        code=r["Project No"].strip()
        if not re.fullmatch(r"P\d{2}-\d+",code): continue
        rows.append((int(r[""]),code,r["Project "].strip(),number(r["Price(CAD)"]),number(r["Physical % Complet "],True),number(r["Financial % Complet"],True),r["status"].strip() or r["status.1"].strip()))
    if not rows: raise ValueError("Empty source")
    return rows
def import_snapshot(conn,text,source_id):
    rows=parse_control(text)
    with conn.transaction():
        conn.execute("DELETE FROM erp.project_snapshots WHERE source_id=%s",(source_id,))
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO erp.project_snapshots(source_id,source_row,project_code,project_title,contract_net,physical_fraction,received_fraction,source_status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",[(source_id,*r) for r in rows])
    return len(rows)
