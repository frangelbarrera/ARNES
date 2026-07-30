"""Tests for arnes.thread."""

from __future__ import annotations

from uuid import uuid4

import pytest

from arnes.thread import Thread
from arnes.thread.events import (
    AssistantMessageEvent,
    EventType,
    RunCompletedEvent,
    StepCompletedEvent,
    StepFailedEvent,
    StepStartedEvent,
    UserMessageEvent,
)


class TestThread:
    """Tests for Thread (append-only event log)."""

    def test_create_empty_thread(self):
        thread = Thread.create()
        assert len(thread) == 0
        assert thread.last() is None
        assert thread.id is not None

    def test_append_mutates_in_place_returns_self(self):
        """Thread.append mutates the events list in place and returns self.

        This replaces the old immutability assertion. The previous
        implementation rebuilt the events list on every append
        (``events=[*self.events, event]``), which was O(N) per append and
        O(N²) for N appends — 1k events ≈ 43ms. The new in-place mutation
        is O(1) per append. ARNES is single-threaded async, so the
        mutation is safe; callers that need to isolate a Thread across
        coroutines (e.g. ``_execute_parallel``) explicitly copy it.
        """
        thread = Thread.create()
        event = UserMessageEvent(
            thread_id=thread.id,
            data={"content": "Hello", "role": "user"},
        )
        returned = thread.append(event)
        # Original IS mutated (append-only, not immutable)
        assert len(thread) == 1
        # append returns self for chaining — same object
        assert returned is thread
        # Event is in the thread
        assert thread.last() == event

    def test_append_rejects_wrong_thread_id(self):
        thread = Thread.create()
        other_id = uuid4()
        event = UserMessageEvent(
            thread_id=other_id,
            data={"content": "Hello"},
        )
        with pytest.raises(ValueError, match="thread_id"):
            thread.append(event)

    def test_extend_multiple_events(self):
        thread = Thread.create()
        events = [
            UserMessageEvent(thread_id=thread.id, data={"content": "Hi"}),
            AssistantMessageEvent(
                thread_id=thread.id,
                data={"content": "Hello", "model": "mock", "tokens_in": 10, "tokens_out": 5},
            ),
        ]
        new_thread = thread.extend(events)
        assert len(new_thread) == 2

    def test_filter_by_type(self):
        thread = Thread.create()
        tid = thread.id
        events = [
            UserMessageEvent(thread_id=tid, data={"content": "Hi"}),
            StepStartedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
            StepCompletedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
            UserMessageEvent(thread_id=tid, data={"content": "Bye"}),
        ]
        thread = thread.extend(events)
        user_msgs = thread.filter_by_type(EventType.USER_MESSAGE)
        assert len(user_msgs) == 2
        steps = thread.filter_by_type(EventType.STEP_STARTED)
        assert len(steps) == 1

    def test_filter_by_step(self):
        thread = Thread.create()
        tid = thread.id
        events = [
            StepStartedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
            StepCompletedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
            StepStartedEvent(thread_id=tid, step_id="s2", data={"step_id": "s2"}),
        ]
        thread = thread.extend(events)
        s1_events = thread.filter_by_step("s1")
        assert len(s1_events) == 2

    def test_reduce_basic(self):
        """Test the stateless reducer."""
        thread = Thread.create()
        tid = thread.id
        events = [
            UserMessageEvent(thread_id=tid, data={"content": "Hi"}),
            AssistantMessageEvent(
                thread_id=tid,
                data={
                    "content": "Hello",
                    "model": "mock",
                    "tokens_in": 10,
                    "tokens_out": 5,
                    "cost_usd": 0.001,
                },
            ),
            StepStartedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
            StepCompletedEvent(
                thread_id=tid,
                step_id="s1",
                data={
                    "step_id": "s1",
                    "output": "result",
                    "duration_s": 0.5,
                    # The reducer now accumulates tokens/cost from
                    # StepCompletedEvent (the per-step aggregate) rather
                    # than from AssistantMessageEvent (the per-call view).
                    # The two values match here because there is exactly
                    # one LLM call in this step.
                    "tokens_in": 10,
                    "tokens_out": 5,
                    "cost_usd": 0.001,
                },
            ),
            RunCompletedEvent(
                thread_id=tid,
                data={
                    "steps_executed": 1,
                    "duration_s": 1.0,
                    "total_tokens": 15,
                    "total_cost_usd": 0.001,
                },
            ),
        ]
        thread = thread.extend(events)
        state = thread.reduce()

        assert len(state["messages"]) == 2
        assert state["messages"][0]["content"] == "Hi"
        assert state["messages"][1]["content"] == "Hello"
        assert state["total_tokens_in"] == 10
        assert state["total_tokens_out"] == 5
        assert state["total_cost_usd"] == 0.001
        assert state["status"] == "completed"
        assert "s1" in state["steps"]
        assert state["steps"]["s1"]["status"] == "completed"
        # Per-step token/cost should also be visible on the step entry itself.
        assert state["steps"]["s1"]["tokens_in"] == 10
        assert state["steps"]["s1"]["tokens_out"] == 5
        assert state["steps"]["s1"]["cost_usd"] == 0.001

    def test_reduce_with_failure(self):
        thread = Thread.create()
        tid = thread.id
        events = [
            StepStartedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
            StepFailedEvent(
                thread_id=tid,
                step_id="s1",
                data={"step_id": "s1", "error": "Boom", "retry": False},
            ),
        ]
        thread = thread.extend(events)
        state = thread.reduce()
        assert state["steps"]["s1"]["status"] == "failed"
        assert state["steps"]["s1"]["error"] == "Boom"
        assert len(state["errors"]) == 1

    def test_to_json_roundtrip(self):
        thread = Thread.create()
        tid = thread.id
        events = [
            UserMessageEvent(thread_id=tid, data={"content": "Hi"}),
        ]
        thread = thread.extend(events)

        json_str = thread.to_json()
        restored = Thread.from_json(json_str)

        assert len(restored) == 1
        assert restored[0].data["content"] == "Hi"
        assert restored.id == thread.id

    def test_save_load_disk(self, tmp_path):
        thread = Thread.create()
        tid = thread.id
        events = [UserMessageEvent(thread_id=tid, data={"content": "Hi"})]
        thread = thread.extend(events)

        path = tmp_path / "thread.json"
        thread.save(path)
        loaded = Thread.load(path)

        assert len(loaded) == 1
        assert loaded.id == thread.id

    def test_to_markdown(self):
        thread = Thread.create()
        tid = thread.id
        events = [
            UserMessageEvent(thread_id=tid, data={"content": "Hi"}),
            StepStartedEvent(thread_id=tid, step_id="s1", data={"step_id": "s1"}),
        ]
        thread = thread.extend(events)
        md = thread.to_markdown()

        assert "Bitácora ARNES" in md
        assert "user_message" in md
        assert "step_started" in md
        assert "s1" in md
