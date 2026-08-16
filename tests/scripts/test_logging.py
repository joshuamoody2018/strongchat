#!/usr/bin/env python3
"""Offline tests for the structured JSONL logging setup.

Covers: env-driven level resolution via :func:`configure_logging`,
idempotent configure, JSON record shape via :class:`JsonFormatter`, and
the non-serializable-extra repr fallback. Test inline construction of
:class:`LogRecord` + :func:`JsonFormatter.format` rather than driving a
real FileHandler from disk, because ``self.assertLogs`` REPLACES the
target logger's handlers with its own capturing handler and would hide
the file-write side-effect we want to assert on.
"""

import json
import logging
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from config import logging as sc_logging


def _make_record(
    msg: str = "llm_call",
    level: int = logging.INFO,
    extra: dict | None = None,
) -> logging.LogRecord:
    """Build a LogRecord with extras set, mirroring what services emit."""
    record = logging.makeLogRecord(
        {
            "name": "strongchat.test",
            "level": level,
            "levelname": logging.getLevelName(level),
            "msg": msg,
            "created": time.time(),
            "msecs": 0,
        }
    )
    if extra:
        for k, v in extra.items():
            setattr(record, k, v)
    return record


class TestJsonFormatter(unittest.TestCase):
    """Formatting-only tests for JsonFormatter."""

    def test_record_serializes_to_one_json_object(self):
        """Each record format returns one JSON object, parseable, with the standard fields."""
        fmt = sc_logging.JsonFormatter()
        record = _make_record(
            extra={
                "event": "llm_call",
                "correlation_id": "c-1",
                "slug": "intent_generation",
                "elapsed_ms": 50,
                "status": "ok",
            }
        )
        out = fmt.format(record)
        # One JSON object on one line (no embedded newlines).
        self.assertEqual(out.count("\n"), 0)
        payload = json.loads(out)
        self.assertEqual(payload["level"], "INFO")
        self.assertEqual(payload["event"], "llm_call")
        self.assertEqual(payload["correlation_id"], "c-1")
        self.assertEqual(payload["slug"], "intent_generation")
        self.assertEqual(payload["elapsed_ms"], 50)
        self.assertEqual(payload["status"], "ok")
        # Timestamp must be present and end with Z (UTC).
        self.assertIn("ts", payload)
        self.assertTrue(payload["ts"].endswith("Z"))

    def test_debug_record_carries_prompt_and_raw_response(self):
        """At DEBUG, the audit payload carries prompt + raw_response fields."""
        fmt = sc_logging.JsonFormatter()
        record = _make_record(
            msg="llm_call_audit",
            level=logging.DEBUG,
            extra={
                "event": "llm_call_audit",
                "correlation_id": "c-2",
                "slug": "hyde_generation",
                "prompt": "<serialized intent>",
                "raw_response": '{ "hyde_document": "..." }',
                "attempts": 1,
            },
        )
        payload = json.loads(fmt.format(record))
        self.assertEqual(payload["level"], "DEBUG")
        self.assertEqual(payload["event"], "llm_call_audit")
        self.assertEqual(payload["prompt"], "<serialized intent>")
        self.assertIn("raw_response", payload)
        self.assertEqual(payload["attempts"], 1)

    def test_non_serializable_extra_is_repr_fallback(self):
        """Non-JSON-serializable extras degrade to repr rather than crashing."""
        fmt = sc_logging.JsonFormatter()
        record = _make_record(
            extra={"event": "ev", "weird": {1, 2, 3}}
        )
        payload = json.loads(fmt.format(record))
        self.assertIn("weird", payload)
        # repr fallback must mention the set syntax.
        self.assertIn("{", str(payload["weird"]))

    def test_exc_info_serialized_into_exc_field(self):
        """An exception attached to the record surfaces as 'exc' in the payload."""
        fmt = sc_logging.JsonFormatter()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            import sys
            record = _make_record()
            record.exc_info = sys.exc_info()
        payload = json.loads(fmt.format(record))
        self.assertIn("exc", payload)
        self.assertIn("RuntimeError", payload["exc"])
        self.assertIn("boom", payload["exc"])

    def test_error_record_carries_error_field(self):
        """At ERROR level, the audit record carries the `error` field verbatim.

        Mirrors what LLMWrapper / EmbeddingService / PipelineRunner emit on
        a failure: ERROR `llm_call` record with `status='error'` and a
        non-empty `error` string. Previously the ERROR level was only
        tested via the default-level check; this asserts the actual record
        shape fires through the formatter correctly.
        """
        fmt = sc_logging.JsonFormatter()
        record = _make_record(
            msg="llm_call",
            level=logging.ERROR,
            extra={
                "event": "llm_call",
                "correlation_id": "c-err",
                "slug": "intent_generation",
                "attempts": 4,
                "elapsed_ms": 900,
                "status": "error",
                "error": "API call failed after 3 attempts: connection reset",
            },
        )
        payload = json.loads(fmt.format(record))
        self.assertEqual(payload["level"], "ERROR")
        self.assertEqual(payload["event"], "llm_call")
        self.assertEqual(payload["correlation_id"], "c-err")
        self.assertEqual(payload["attempts"], 4)
        self.assertEqual(payload["status"], "error")
        self.assertIn("error", payload)
        self.assertIn("connection reset", payload["error"])
        # Timestamp is still present on ERROR records.
        self.assertTrue(payload["ts"].endswith("Z"))


class TestConfigureLogging(unittest.TestCase):
    """Tests for configure_logging level resolution + idempotency."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_file = os.path.join(self._tmp.name, "strongchat_test.log")
        logger = logging.getLogger("strongchat")
        for h in list(logger.handlers):
            logger.removeHandler(h)
        if hasattr(logger, "_strongchat_configured"):
            del logger._strongchat_configured  # type: ignore[attr-defined]

    def tearDown(self):
        logger = logging.getLogger("strongchat")
        for h in list(logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            logger.removeHandler(h)
        if hasattr(logger, "_strongchat_configured"):
            del logger._strongchat_configured  # type: ignore[attr-defined]
        self._tmp.cleanup()

    def test_default_level_is_error_when_env_unset(self):
        """Without STRONGCHAT_LOG_LEVEL set, the root logger level is ERROR."""
        prev = os.environ.pop("STRONGCHAT_LOG_LEVEL", None)
        try:
            sc_logging.configure_logging(log_file=self.log_file)
            self.assertEqual(logging.getLogger("strongchat").level, logging.ERROR)
        finally:
            if prev is not None:
                os.environ["STRONGCHAT_LOG_LEVEL"] = prev

    def test_explicit_info_level_sets_root_to_info(self):
        sc_logging.configure_logging(level="INFO", log_file=self.log_file)
        self.assertEqual(logging.getLogger("strongchat").level, logging.INFO)

    def test_configure_logging_is_idempotent(self):
        """Calling configure twice does not stack duplicate file handlers."""
        sc_logging.configure_logging(level="INFO", log_file=self.log_file)
        sc_logging.configure_logging(level="INFO", log_file=self.log_file)
        file_handlers = [
            h for h in logging.getLogger("strongchat").handlers
            if hasattr(h, "baseFilename")
        ]
        # Exactly one file-ish handler (stderr StreamHandler has no baseFilename).
        self.assertEqual(len(file_handlers), 1)

    def test_get_logger_coerces_names_into_strongchat_hierarchy(self):
        """Names not already prefixed with 'strongchat' land under 'strongchat.*'."""
        sc_logging.configure_logging(level="INFO", log_file=self.log_file)
        # An unrelated logger name gets coerced.
        coerced = sc_logging.get_logger("services.embeddings.service")
        self.assertEqual(coerced.name, "strongchat.services.embeddings.service")
        # Already-prefixed names are not double-prefixed.
        explicit = sc_logging.get_logger("strongchat.explicit")
        self.assertEqual(explicit.name, "strongchat.explicit")
        # The root default is exactly "strongchat".
        root = sc_logging.get_logger()
        self.assertEqual(root.name, "strongchat")

    def test_error_record_lands_on_disk_via_real_logger(self):
        """An ERROR emitted through a real logger lands as JSON on disk.

        Drives the actual configure_logging -> ConcurrentRotatingFileHandler
        -> file path so we exercise cross-process-safe writes end-to-end.
        (Cannot use assertLogs here - it REPLACES the logger's handlers with
        its own capture handler and would hide the file-write side effect we
        need to verify; the ERROR formatter-shape test above covers the format
        side via JsonFormatter.format directly.)
        """
        sc_logging.configure_logging(level="ERROR", log_file=self.log_file)
        logger = sc_logging.get_logger("strongchat.test")
        logger.error(
            "llm_call",
            extra={
                "event": "llm_call",
                "correlation_id": "c-live-err",
                "slug": "intent_generation",
                "status": "error",
                "error": "live failure",
            },
        )
        # Close file-ish handlers so the lazy-open + fcntl lock path flushes
        # the record to disk before we read it back.
        for h in logging.getLogger("strongchat").handlers:
            if hasattr(h, "baseFilename"):
                try:
                    h.flush()
                    h.close()
                except Exception:
                    pass

        self.assertTrue(
            os.path.exists(self.log_file),
            "ERROR log file was not created - handler did not write",
        )
        with open(self.log_file, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)
        payload = json.loads(lines[0])
        self.assertEqual(payload["level"], "ERROR")
        self.assertEqual(payload["event"], "llm_call")
        self.assertEqual(payload["correlation_id"], "c-live-err")
        self.assertEqual(payload["status"], "error")
        self.assertEqual(payload["error"], "live failure")


if __name__ == "__main__":
    unittest.main(verbosity=2)