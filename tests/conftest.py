from collections import deque

import pytest
from langchain_core.messages import AIMessage

from bbdevbox.config import Config
from bbdevbox.store import Store


class ScriptedModel:
    """Exercises the actual LangGraph/tool loop without network or billed tokens."""
    def __init__(self, responses):
        self.responses = deque(responses)
        self.requests = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages, **kwargs):
        self.requests.append(messages)
        result = self.responses.popleft()
        if isinstance(result, Exception):
            raise result
        if callable(result):
            result = result(messages)
        return result


def answer(text="done", tools=None, usage=True):
    return AIMessage(content=text, tool_calls=tools or [], usage_metadata={
        "input_tokens": 7, "output_tokens": 3, "total_tokens": 10} if usage else None)


def tool(name, args, key="call-1"):
    return {"name": name, "args": args, "id": key, "type": "tool_call"}


@pytest.fixture
def config():
    c = Config()
    c.sandbox.backend = "local"
    c.sandbox.allow_local = True
    return c


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "runs")
