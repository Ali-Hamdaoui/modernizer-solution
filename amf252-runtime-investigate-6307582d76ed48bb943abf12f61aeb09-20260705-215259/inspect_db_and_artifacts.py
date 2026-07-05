import json, os, sqlite3, glob

JOB = os.environ["AMF_JOB"]
OUT = os.environ["AMF_OUT"]
DB = r".control-tower-dev\control_tower.sqlite3"

def save(name, obj):
    path = os.path.join(OUT, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False, default=str)
    print("saved:", path)

def rows(cur, sql, args=()):
    try:
        cur.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    except Exception as e:
        return [{"error": str(e), "sql": sql}]

if not os.path.exists(DB):
    save("db-error.json", {"error": "DB not found", "db": DB})
    raise SystemExit(0)

con = sqlite3.connect(DB)
cur = con.cursor()

tables = rows(cur, "select name from sqlite_master where type='table' order by name")
save("db-tables.json", tables)

table_names = {r.get("name") for r in tables}

for t in sorted(table_names):
    if not t:
        continue
    schema = rows(cur, f"pragma table_info({t})")
    save(f"schema-{t}.json", schema)

for t in sorted(table_names):
    if not t:
        continue
    cols = [c.get("name") for c in rows(cur, f"pragma table_info({t})")]
    if "job_id" in cols:
        data = rows(cur, f"select * from {t} where job_id=? order by rowid desc limit 200", (JOB,))
        if data:
            save(f"db-{t}.json", data)

for t in ("events", "v2_events", "control_tower_events", "migration_events"):
    if t in table_names:
        save(f"db-focused-{t}.json", rows(cur, f"select * from {t} where job_id=? order by rowid asc", (JOB,)))

matches = []
for pat in [
    f".control-tower-dev/**/*{JOB}*",
    f".control-tower-dev/**/reviewer_repair_llm_output.json",
    f".control-tower-dev/**/reviewer_repair_schema_failure.json",
    f".control-tower-dev/**/review_chain.json",
    f".control-tower-dev/**/final_reviewed_repair.diff",
    f".control-tower-dev/**/backend_import_replacement.diff",
]:
    matches.extend(glob.glob(pat, recursive=True))

save("file-matches.json", sorted(set(matches)))

for p in sorted(set(matches)):
    if os.path.isfile(p) and os.path.basename(p) in {
        "reviewer_repair_llm_output.json",
        "reviewer_repair_schema_failure.json",
        "review_chain.json",
        "final_reviewed_repair.diff",
        "backend_import_replacement.diff",
        "primary_repair_llm_output.json",
    }:
        safe = p.replace("\\", "__").replace("/", "__").replace(":", "")
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            with open(os.path.join(OUT, "artifact-" + safe), "w", encoding="utf-8") as f:
                f.write(content)
            print("copied artifact:", p)
        except Exception as e:
            print("copy failed:", p, e)

con.close()
print("Done.")
