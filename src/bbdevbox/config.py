"""Strict, serializable configuration. Credentials are read only from the environment."""
import math
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class ModelConfig:
    name: str = "your-tool-calling-model"
    base_url: str | None = None
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float | None = None
    max_output_tokens: int = 4096
    timeout: float = 120
    retries: int = 2
    extra_body: dict = field(default_factory=dict)


@dataclass
class SandboxConfig:
    backend: str = "docker"
    runtime: str | None = None
    network: str = "none"
    memory: str = "2g"
    cpus: float = 2
    pids_limit: int = 256
    build_timeout: float = 600
    command_timeout: float = 60
    allow_local: bool = False


@dataclass
class ContextConfig:
    max_input_tokens: int = 24000
    keep_recent_turns: int = 3
    output_chars: int = 12000
    chunk_chars: int = 6000
    summary_chars: int = 5000
    llm_summary: bool = False


@dataclass
class AgentConfig:
    max_steps: int = 40
    max_tokens: int = 150000
    max_seconds: float = 1200
    multi_agent: bool = False
    max_delegations: int = 3
    child_steps: int = 8
    allow_prompt_updates: bool = False


@dataclass
class MemoryConfig:
    mode: str = "off"  # off | frozen | continual
    collection: str = "default"
    top_k: int = 3
    max_chars: int = 6000


@dataclass
class Config:
    model: ModelConfig = field(default_factory=ModelConfig)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    workers: int = 1
    attempts: int = 1
    seed: int = 42
    prompt_file: str | None = None
    prompt_reload: bool = False

    @classmethod
    def load(cls, path: str | None = None):
        raw = yaml.safe_load(Path(path).read_text()) if path else {}
        if not isinstance(raw, dict):
            raise ValueError("Configuration must be a YAML mapping")
        sections = {"model": ModelConfig, "sandbox": SandboxConfig, "context": ContextConfig,
                    "agent": AgentConfig, "memory": MemoryConfig}
        unknown = set(raw) - {f.name for f in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown configuration keys: {sorted(unknown)}")
        obj = cls(**{k: sections[k](**v) if k in sections else v for k, v in raw.items()})
        obj.validate()
        return obj

    def validate(self):
        integral = [self.workers, self.attempts, self.seed, self.agent.max_steps, self.agent.max_tokens,
                    self.agent.child_steps, self.agent.max_delegations, self.model.max_output_tokens,
                    self.model.retries, self.context.max_input_tokens, self.context.keep_recent_turns,
                    self.context.output_chars, self.context.chunk_chars, self.context.summary_chars,
                    self.memory.top_k, self.memory.max_chars, self.sandbox.pids_limit]
        if any(type(x) is not int for x in integral):
            raise ValueError("Counts, token/character limits and seed must be integers")
        flags = [self.prompt_reload, self.sandbox.allow_local, self.context.llm_summary,
                 self.agent.multi_agent, self.agent.allow_prompt_updates]
        if any(type(x) is not bool for x in flags):
            raise ValueError("Feature flags must be YAML booleans")
        if self.sandbox.backend not in {"docker", "podman", "local"}:
            raise ValueError("sandbox.backend must be docker, podman, or local")
        if self.sandbox.backend == "local" and not self.sandbox.allow_local:
            raise ValueError("local executes on the HOST; explicitly set sandbox.allow_local: true")
        if self.memory.mode not in {"off", "frozen", "continual"}:
            raise ValueError("memory.mode must be off, frozen, or continual")
        if self.sandbox.network not in {"none", "bridge"}:
            raise ValueError("sandbox.network must be none or bridge")
        positive = [self.workers, self.attempts, self.agent.max_steps, self.agent.max_tokens,
                    self.agent.max_seconds, self.agent.child_steps, self.context.max_input_tokens,
                    self.context.output_chars, self.context.chunk_chars, self.context.summary_chars,
                    self.sandbox.command_timeout, self.sandbox.build_timeout, self.sandbox.cpus,
                    self.sandbox.pids_limit, self.model.max_output_tokens, self.model.timeout,
                    self.memory.top_k, self.memory.max_chars, self.context.keep_recent_turns]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or x <= 0
               for x in positive):
            raise ValueError("Budgets, limits, workers, and attempts must be positive numbers")
        if self.model.retries < 0 or self.agent.max_delegations < 0:
            raise ValueError("Retry and delegation limits cannot be negative")

    def as_dict(self):
        return asdict(self)
