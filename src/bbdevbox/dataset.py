import hashlib
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Task:
    uuid: str
    problem: str
    verification: str
    dockerfile_content: str = ""
    subdomain: str = "general"
    keyword: str = ""
    level: str = "unknown"
    setup: str = ""

    def render(self, seed: int, attempt: int):
        # Independent of task scheduling and Python's randomized hash seed.
        digest = hashlib.sha256(f"{seed}:{self.uuid}:{attempt}".encode()).hexdigest()
        value = str(random.Random(digest).randint(10000, 99999))
        return Task(**{k: v.replace("${random_num}", value).replace("$random_num", value)
                       if isinstance(v, str) else v for k, v in asdict(self).items()})


def load_tasks(path: str) -> list[Task]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError("Dataset must be a nonempty YAML list")
    tasks = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict):
            raise ValueError("Each task must be a mapping")
        for key in ("uuid", "problem", "verification"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"Task requires nonempty string {key}")
        if row["uuid"] in seen:
            raise ValueError(f"Duplicate task UUID: {row['uuid']}")
        seen.add(row["uuid"])
        fields = Task.__dataclass_fields__
        task = Task(**{k: v for k, v in row.items() if k in fields})
        if any(not isinstance(v, str) for v in asdict(task).values()):
            raise ValueError(f"Task fields must be strings: {task.uuid}")
        tasks.append(task)
    return tasks


def fingerprint(tasks: list[Task]) -> str:
    payload = json.dumps([asdict(t) for t in tasks], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()
