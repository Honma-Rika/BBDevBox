"""Explicitly promoted, provenance-carrying SOP memory with SQLite FTS5 retrieval."""
import re
import time
import uuid


class Knowledge:
    def __init__(self, store, collection="default"):
        self.store = store
        self.collection = collection

    def snapshot(self):
        with self.store.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM memories WHERE approved=1 AND collection=? "
                                             "ORDER BY id", (self.collection,))]

    def propose(self, task_id, domain, text, source_attempt, kind="skill"):
        if kind not in {"skill", "memory", "prompt"}:
            raise ValueError("Unknown knowledge kind")
        if not text.strip() or len(text) > 30000:
            raise ValueError("Knowledge must be nonempty and at most 30000 characters")
        key = uuid.uuid4().hex
        with self.store.connect() as db:
            db.execute("INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?)",
                       (key, time.time(), self.collection, task_id, domain, kind, text, 0, source_attempt))
            db.execute("INSERT INTO memories_fts(id,text) VALUES (?,?)", (key, text))
        return key

    def list(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM memories WHERE collection=? ORDER BY created",
                                               (self.collection,))]

    def promote(self, key):
        with self.store.connect() as db:
            row = db.execute("SELECT m.*,a.status FROM memories m JOIN attempts a ON a.id=m.source_attempt "
                             "WHERE m.id=? AND m.collection=?", (key, self.collection)).fetchone()
            if row is None or row["status"] != "passed":
                raise ValueError("Only knowledge from a verification-passed attempt can be promoted")
            # Export first: failure must not create approved but unexported SOPs.
            target = self.store.root / "skills" / key
            target.mkdir(parents=True, exist_ok=True)
            filename = "SKILL.md" if row["kind"] == "skill" else f"{row['kind']}.md"
            path = target / filename
            path.write_text(f"<!-- source_task={row['task_id']} source_attempt={row['source_attempt']} "
                            f"collection={self.collection} -->\n\n{row['text']}\n", encoding="utf-8")
            db.execute("UPDATE memories SET approved=1 WHERE id=?", (key,))
        return path

    def search(self, query, task_id, snapshot=None, top_k=3, max_chars=6000, domain=None):
        terms = re.findall(r"[^\W_]+", query, flags=re.UNICODE)[:32]
        if not terms or snapshot == []:
            return []
        match = " OR ".join('"' + t + '"' for t in terms)
        params = [match, self.collection, task_id]
        clause = ""
        if domain:
            clause += " AND m.domain=?"
            params.append(domain)
        if snapshot is not None:
            # JSON1 avoids SQLite's variable-count limit for large frozen corpora.
            import json
            clause += " AND m.id IN (SELECT value FROM json_each(?))"
            params.append(json.dumps(snapshot))
        with self.store.connect() as db:
            rows = db.execute("SELECT m.*,bm25(memories_fts) AS rank FROM memories_fts "
                              "JOIN memories m ON m.id=memories_fts.id WHERE memories_fts MATCH ? "
                              "AND m.approved=1 AND m.collection=? AND m.task_id!=? " + clause +
                              " ORDER BY rank,m.id LIMIT ?", (*params, top_k)).fetchall()
        result = []
        remaining = max_chars
        for row in rows:
            if remaining <= 0:
                break
            item = dict(row)
            item["text"] = item["text"][:remaining]
            remaining -= len(item["text"])
            result.append(item)
        return result
