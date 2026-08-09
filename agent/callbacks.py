# agent/callbacks.py
"""Streaming callback — captures agent thinking and tool calls in real-time.

Surfaces tool execution events, LLM token streaming, and chain-of-thought
reasoning for UI rendering.
"""
import time
from typing import Any
from langchain_core.callbacks import BaseCallbackHandler
from utils.logger import get_logger

logger = get_logger(__name__)


class StreamingCallback(BaseCallbackHandler):
    """LangChain callback that captures agent events for real-time UI updates.

    Writes to a shared dict (session_state._stream_events) that the UI polls.
    Each event: {type, timestamp, data, ...}
    """

    def __init__(self, event_sink: dict | None = None):
        """event_sink: optional dict for UI events. None = logged only."""
        super().__init__()
        self._sink = event_sink or {}
        self._events: list[dict] = []
        self._tool_start_times: dict[str, float] = {}
        self._current_tool: str = ""

    @property
    def events(self) -> list[dict]:
        return self._events

    def clear(self):
        self._events.clear()
        self._tool_start_times.clear()
        self._current_tool = ""

    # ── LLM events ──

    def on_llm_start(self, serialized: dict[str, Any], prompts: list[str],
                     **kwargs: Any) -> None:
        self._add_event("llm_start", {
            "prompt_len": sum(len(p) for p in prompts),
        })

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        gen = getattr(response, "generations", [[]])
        text = ""
        if gen and gen[0]:
            text = getattr(gen[0][0], "text", "")[:100]
        self._add_event("llm_end", {
            "preview": text,
        })

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        self._add_event("llm_error", {"error": str(error)[:200]})

    # ── Tool events ──

    def on_tool_start(self, serialized: dict[str, Any], input_str: str,
                      **kwargs: Any) -> None:
        tool_name = serialized.get("name", "unknown")
        self._current_tool = tool_name
        self._tool_start_times[tool_name] = time.time()
        self._add_event("tool_start", {
            "tool": tool_name,
            "input_preview": input_str[:120],
        })

    def on_tool_end(self, output: Any, **kwargs: Any) -> None:
        tool_name = self._current_tool
        elapsed = 0.0
        if tool_name in self._tool_start_times:
            elapsed = time.time() - self._tool_start_times.pop(tool_name)
        output_str = str(output)[:200] if output else ""
        self._add_event("tool_end", {
            "tool": tool_name,
            "output_preview": output_str,
            "elapsed_ms": round(elapsed * 1000, 0),
        })
        self._current_tool = ""

    def on_tool_error(self, error: BaseException, **kwargs: Any) -> None:
        self._add_event("tool_error", {
            "tool": self._current_tool,
            "error": str(error)[:200],
        })
        self._current_tool = ""

    # ── Chain / Agent events ──

    def on_agent_action(self, action: Any, **kwargs: Any) -> None:
        self._add_event("agent_action", {
            "tool": getattr(action, "tool", "unknown"),
            "log": getattr(action, "log", "")[:200],
        })

    def on_agent_finish(self, finish: Any, **kwargs: Any) -> None:
        self._add_event("agent_finish", {
            "output_preview": str(getattr(finish, "return_values", {}))[:200],
        })

    def on_chain_start(self, serialized: dict[str, Any], inputs: dict[str, Any],
                       **kwargs: Any) -> None:
        self._add_event("chain_start", {
            "chain": serialized.get("name", serialized.get("id", ["Unknown"])[-1]),
        })

    def on_chain_end(self, outputs: dict[str, Any], **kwargs: Any) -> None:
        self._add_event("chain_end", {})

    # ── Internal ──

    def _add_event(self, etype: str, data: dict):
        event = {
            "type": etype,
            "timestamp": time.time(),
            **data,
        }
        self._events.append(event)

        # Push to shared sink if available
        if self._sink is not None:
            if "_stream_events" not in self._sink:
                self._sink["_stream_events"] = []
            self._sink["_stream_events"].append(event)
            self._sink["_stream_current_tool"] = self._current_tool

    def get_tool_timeline(self) -> list[dict]:
        """Return a timeline of tool calls with durations for UI display."""
        timeline: list[dict] = []
        current: dict | None = None
        for ev in self._events:
            if ev["type"] == "tool_start":
                current = {"tool": ev["tool"], "start": ev["timestamp"],
                           "input": ev.get("input_preview", "")}
            elif ev["type"] == "tool_end" and current and ev["tool"] == current["tool"]:
                current["end"] = ev["timestamp"]
                current["elapsed_ms"] = ev.get("elapsed_ms", 0)
                current["output"] = ev.get("output_preview", "")
                timeline.append(current)
                current = None
            elif ev["type"] == "tool_error" and current:
                current["error"] = ev.get("error", "")
                timeline.append(current)
                current = None
        return timeline
