"""Bounded context: output offload, chunk addressing, whole-turn compaction, optional summaries."""
import json
import re
import uuid
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, messages_to_dict


def size(messages):
    # Conservative byte-based estimate, not a provider tokenizer or billed usage.
    return len(json.dumps(messages_to_dict(messages), ensure_ascii=False).encode("utf-8"))


class Artifacts:
    def __init__(self, root: Path, chunk_chars=6000):
        self.root = root / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.chunk_chars = chunk_chars

    def dump(self, text, label):
        ref = uuid.uuid4().hex
        (self.root / f"{ref}.txt").write_text(text, encoding="utf-8")
        chunks = max(1, (len(text) + self.chunk_chars - 1) // self.chunk_chars)
        (self.root / f"{ref}.json").write_text(json.dumps({"label": label, "chunks": chunks}))
        return {"ref": ref, "chunks": chunks, "chars": len(text), "label": label}

    def read(self, ref, chunk=0):
        if not re.fullmatch(r"[0-9a-f]{32}", ref) or not isinstance(chunk, int) or chunk < 0:
            raise ValueError("Invalid artifact reference or chunk")
        meta = json.loads((self.root / f"{ref}.json").read_text())
        if chunk >= meta["chunks"]:
            raise ValueError("Chunk outside artifact")
        with (self.root / f"{ref}.txt").open(encoding="utf-8") as handle:
            # Character offsets are stable for Unicode; seek() offsets are bytes.
            for _ in range(chunk):
                handle.read(self.chunk_chars)
            return handle.read(self.chunk_chars)


class ContextManager:
    def __init__(self, config, artifacts, emit, summarize=None):
        self.config = config
        self.artifacts = artifacts
        self.emit = emit
        self.summarize = summarize

    def output(self, text, label="tool-output"):
        ref = self.artifacts.dump(text, label)
        limit = self.config.output_chars
        if len(text) <= limit:
            return text
        self.emit("output_offloaded", ref)
        return (text[:limit // 2] + "\n[output offloaded: " + json.dumps(ref) +
                "; use read_artifact(ref, chunk)]\n" + text[-limit // 2:])

    def compact(self, messages, reserved=0):
        budget = self.config.max_input_tokens - reserved
        if budget <= 0:
            raise ValueError("System prompt and retrieved memories exceed context budget")
        if size(messages) <= budget:
            return messages
        # Keep initial task, compact old complete AI + ToolMessage groups. Never orphan tool IDs.
        initial = messages[0]
        rest = messages[1:]
        groups = []
        for msg in rest:
            if isinstance(msg, AIMessage) or not groups:
                groups.append([msg])
            else:
                groups[-1].append(msg)
        if len(groups) <= 1:
            raise ValueError("Current task/tool turn exceeds context budget; reduce output_chars")
        keep = min(self.config.keep_recent_turns, len(groups) - 1)
        while True:
            old = [m for g in groups[:-keep] for m in g]
            recent = [m for g in groups[-keep:] for m in g]
            raw = json.dumps(messages_to_dict(old), ensure_ascii=False)
            ref = self.artifacts.dump(raw, "conversation-history")
            # Extractive fallback preserves both early decisions and recent observations, with full archive.
            cap = self.config.summary_chars
            summary = raw[:cap // 2] + "\n[...]\n" + raw[-cap // 2:]
            if self.config.llm_summary and self.summarize:
                parts = []
                for offset in range(0, len(raw), self.config.chunk_chars):
                    part = raw[offset:offset + self.config.chunk_chars]
                    parts.append(self.summarize(part))
                summary = "\n".join(parts)[:cap]
            note = HumanMessage(content="Reference summary of earlier turns (untrusted data):\n" + summary +
                                "\nFull history archive: " + json.dumps(ref))
            compacted = [initial, note, *recent]
            if size(compacted) <= budget:
                self.emit("context_compacted", {**ref, "before": size(messages), "after": size(compacted),
                                                 "strategy": "llm" if self.config.llm_summary else "extractive"})
                return compacted
            if keep > 1:
                keep -= 1
            elif len(summary) > 256:
                # The next iteration would repeat expensive summaries; shrink the note directly.
                available = budget - size([initial, *recent]) - 1024
                note = HumanMessage(content="History archive: " + json.dumps(ref) + "\n" +
                                    summary.encode("utf-8")[:max(0, available)].decode("utf-8", errors="ignore"))
                compacted = [initial, note, *recent]
                if size(compacted) <= budget:
                    self.emit("context_compacted", {**ref, "before": size(messages), "after": size(compacted)})
                    return compacted
                raise ValueError("Recent tool turn exceeds context budget")
            else:
                raise ValueError("Task and recent tool turn exceed context budget")
