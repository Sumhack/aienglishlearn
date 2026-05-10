from __future__ import annotations

import unittest
from importlib.util import find_spec
from types import SimpleNamespace
from unittest.mock import patch

from app.logging.context import clear_context, get_context_data, set_context
from app.logging.events import REQUEST_STARTED, WARMUP_STARTED, is_valid_event
from app.logging.schema import normalize_log_record


class LoggingEventTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_context()

    def test_request_event_is_valid(self) -> None:
        self.assertTrue(is_valid_event(REQUEST_STARTED))

    def test_warmup_event_is_valid(self) -> None:
        self.assertTrue(is_valid_event(WARMUP_STARTED))


class LoggingSchemaTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_context()

    def test_normalize_adds_defaults(self) -> None:
        record = normalize_log_record({"event": "request.started", "status": "started"})
        self.assertEqual(record["schema_version"], "v1")
        self.assertEqual(record["level"], "INFO")
        self.assertEqual(record["service"], "app")
        self.assertEqual(record["source"], "app")
        self.assertEqual(record["trace_id"], "unknown")
        self.assertIn("timestamp", record)


class LoggingWrapperTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_context()

    def test_log_event_merges_context_and_invalid_event_metadata(self) -> None:
        if find_spec("structlog") is None:
            self.skipTest("structlog is not installed in this test environment")

        from app.logging.wrapper import log_event

        emitted: dict[str, object] = {}

        class DummyLogger:
            def info(self, **kwargs):
                emitted.update(kwargs)

        with patch("app.logging.wrapper.get_logger", return_value=DummyLogger()):
            set_context(trace_id="trace-1", session_id="sess-1")

            log_event(event="not.valid", status="started", message="hello", method="GET")

        self.assertEqual(emitted["event"], "invalid.event")
        self.assertEqual(emitted["invalid_event"], "not.valid")
        self.assertEqual(emitted["trace_id"], "trace-1")
        self.assertEqual(emitted["session_id"], "sess-1")
        self.assertEqual(emitted["method"], "GET")

    def test_log_error_uses_error_message_not_legacy_error_key(self) -> None:
        if find_spec("structlog") is None:
            self.skipTest("structlog is not installed in this test environment")

        from app.logging.wrapper import log_error

        emitted: dict[str, object] = {}

        class DummyLogger:
            def error(self, **kwargs):
                emitted.update(kwargs)

        with patch("app.logging.wrapper.get_logger", return_value=DummyLogger()):
            log_error(
                event="request.failed",
                status="failed",
                message="Request failed",
                error_message="boom",
                error_type="internal",
                error_stage="ingest",
            )

        self.assertEqual(emitted["error_message"], "boom")
        self.assertNotIn("error", emitted)


class LoggingMiddlewareTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_context()

    def test_middleware_adds_trace_header(self) -> None:
        if find_spec("fastapi") is None or find_spec("structlog") is None:
            self.skipTest("fastapi/structlog are not installed in this test environment")

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.middleware.logging_middleware import LoggingMiddleware

        app = FastAPI()
        app.add_middleware(LoggingMiddleware)

        with patch("app.middleware.logging_middleware.log_boundary") as log_boundary_mock, patch(
            "app.middleware.logging_middleware.log_error"
        ) as log_error_mock:

            @app.get("/health")
            async def health():
                return {"ok": True}

            with TestClient(app) as client:
                response = client.get("/health", headers={"x-trace-id": "trace-123"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-trace-id"], "trace-123")
        self.assertTrue(log_boundary_mock.called)
        self.assertFalse(log_error_mock.called)


class MainLoggingTests(unittest.IsolatedAsyncioTestCase):
    def tearDown(self) -> None:
        clear_context()

    async def test_start_session_logs_auth_failed_with_contract_fields(self) -> None:
        if find_spec("fastapi") is None:
            self.skipTest("fastapi is not installed in this test environment")

        from fastapi import HTTPException
        from app.main import SessionStartRequest, start_session

        with patch("app.main.log_error") as log_error_mock:
            with self.assertRaises(HTTPException) as exc_info:
                await start_session(SessionStartRequest(persona="coach"), authorization=None)

        self.assertEqual(exc_info.exception.status_code, 401)
        _, kwargs = log_error_mock.call_args
        self.assertEqual(kwargs["event"], "auth.failed")
        self.assertEqual(kwargs["status_code"], 401)
        self.assertEqual(kwargs["error_type"], "auth")
        self.assertEqual(kwargs["error_stage"], "auth")
        self.assertIn("error_message", kwargs)
        self.assertNotIn("error", kwargs)

    async def test_finalize_session_logs_non_zero_duration(self) -> None:
        if find_spec("fastapi") is None:
            self.skipTest("fastapi is not installed in this test environment")

        from app.main import finalize_session

        fake_settings = SimpleNamespace(internal_api_key="test-key")
        fake_session = SimpleNamespace(user_id="u1", persona="traveler")
        fake_result = SimpleNamespace(
            scores={"overall": 80, "fluency": 75, "grammar": 82, "vocabulary": 79, "clarity": 83, "relevance": 81},
            strengths=[],
            improvements=[],
            content_improvements=[],
            practice_tasks=[],
            corrections=[],
            notes=[],
        )

        with patch("app.main.get_settings", return_value=fake_settings), patch(
            "app.main.get_session_by_id", return_value=fake_session
        ), patch("app.main.list_turn_items", return_value=[]), patch(
            "app.main.build_session_eval_prompt", return_value="prompt"
        ), patch(
            "app.main.run_deep_eval", return_value=fake_result
        ), patch(
            "app.main.update_session_summary"
        ), patch(
            "app.main.log_boundary"
        ) as log_boundary_mock:
            await finalize_session(
                session_id="sess-1",
                authorization=None,
                x_internal_key="test-key",
            )

        completed_calls = [
            call for call in log_boundary_mock.call_args_list if call.kwargs.get("event") == "evaluation.completed"
        ]
        self.assertEqual(len(completed_calls), 1)
        self.assertIn("duration_ms", completed_calls[0].kwargs)
        self.assertGreaterEqual(completed_calls[0].kwargs["duration_ms"], 0)

    def test_context_binding_inherits_fields(self) -> None:
        if find_spec("structlog") is None:
            self.skipTest("structlog is not installed in this test environment")

        from app.logging.wrapper import bind_context, log_boundary

        emitted: dict[str, object] = {}

        class DummyLogger:
            def info(self, **kwargs):
                emitted.update(kwargs)

        with patch("app.logging.wrapper.get_logger", return_value=DummyLogger()):
            bind_context(trace_id="trace-1", user_id="user-1", session_id="sess-1", persona="traveler")
            log_boundary(event="session.started", status="started", message="Session created")

        self.assertEqual(emitted["trace_id"], "trace-1")
        self.assertEqual(emitted["user_id"], "user-1")
        self.assertEqual(emitted["session_id"], "sess-1")
        self.assertEqual(emitted["persona"], "traveler")


if __name__ == "__main__":
    unittest.main()
