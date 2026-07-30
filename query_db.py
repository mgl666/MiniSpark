import sqlite3, json, sys
from pathlib import Path

db = Path(r"e:\OneDrive\Project\MiniTools\MiniSpark\minispark\memory\minispark.db")
c = sqlite3.connect(str(db))
c.row_factory = sqlite3.Row

msgs = c.execute("SELECT role, content FROM messages WHERE session_id='qq' AND compacted=0 ORDER BY id").fetchall()

out = []
for r in msgs:
    data = json.loads(r["content"])
    role = r["role"]
    text = data.get("content") or ""
    low = (text + str(data)).lower()
    if any(kw in low for kw in ["email", "send_email", "mail", "send", "发送", "邮件", "女朋友"]):
        out.append(f"[{role}] {text[:500]}")
        if data.get("tool_calls"):
            for tc in data["tool_calls"]:
                fn = tc.get("function", {})
                out.append(f"  -> tool_call: {fn.get('name')} args={fn.get('arguments','')[:300]}")
        if data.get("name"):
            out.append(f"  -> tool_result: {data.get('name')} = {text[:300]}")
        out.append("---")

result = "\n".join(out) if out else "no matching messages found"

with open(r"e:\OneDrive\Project\MiniTools\MiniSpark\query_result.txt", "w", encoding="utf-8") as f:
    f.write(result)

c.close()
print("output written to query_result.txt")