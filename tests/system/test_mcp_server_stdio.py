#!/usr/bin/env python3
"""Live stdio round-trip test for the StrongChat MCP server.

Spawns ``src/server.py`` as a subprocess and drives the MCP JSON-RPC
handshake over its stdin/stdout pipes:

    1. ``initialize`` -> server returns its capabilities + protocol version
    2. ``notifications/initialized`` -> no response expected
    3. ``tools/list`` -> server lists both ``retrieve_context`` and
       ``validate_answer``
    4. ``tools/call validate_answer`` -> server returns an error response
       containing the NotImplementedError contract (the stub raises, which
       the MCP server surfaces as a CallToolResult with isError=true or a
       JSON-RPC error; we accept either since both are observable proof the
       tool was actually invoked end-to-end through the stdio transport).

Step 4 specifically tests the stub offline: it doesn't need
``OPENROUTER_API_KEY`` or an ingested ChromaDB because
``validate_answer_impl`` raises before anything else runs.

``retrieve_context`` itself is NOT invoked here because doing so would
need a real OpenRouter API key + fully-ingested ChromaDB + Macula
assets. That coverage lives in the existing
``tests/system/test_pipeline_e2e.py`` (run via the in-process ``PipelineRunner``
rather than the stdio transport — the transport is a thin pass-through
and is adequately covered by the ``validate_answer`` round-trip below).

Run with the environment loaded:
    set -a; . ./.env; set +a
    .venv/bin/python tests/system/test_mcp_server_stdio.py
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from typing import Any


SERVER_PATH = os.path.join("src", "server.py")
PYTHON = os.environ.get("STRONGCHAT_TEST_PYTHON", ".venv/bin/python")


def _send(proc: subprocess.Popen, obj: dict[str, Any]) -> None:
    """Send one JSON-RPC message (newline-delimited) to the server stdin."""
    line = json.dumps(obj) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(line.encode("utf-8"))
    proc.stdin.flush()


def _recv(proc: subprocess.Popen, timeout: float = 5.0) -> dict[str, Any]:
    """Read one newline-delimited JSON-RPC message from the server stdout."""
    assert proc.stdout is not None
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if not line:
            # Process exited or closed stdout; bail out.
            err = ""
            if proc.stderr is not None:
                err = proc.stderr.read().decode("utf-8", "replace")
            raise AssertionError(
                f"server stdout closed before a response arrived. "
                f"stderr (truncated): {err[:2000]}"
            )
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            # Skip any non-JSON noise (e.g. banner lines).
            continue
    raise AssertionError(
        f"timed out after {timeout}s waiting for a JSON-RPC response from the server"
    )


def _expect_response_matching_id(
    proc: subprocess.Popen, expected_id: int, timeout: float = 5.0
) -> dict[str, Any]:
    """Read messages until we get the JSON-RPC response with `expected_id`.

    The server may emit log lines or notifications interleaved with the
    response; we skip anything that's not a response with the matching id.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = _recv(proc, timeout=max(0.5, deadline - time.monotonic()))
        if msg.get("id") == expected_id and ("result" in msg or "error" in msg):
            return msg
    raise AssertionError(
        f"timed out waiting for response with id={expected_id}"
    )


async def run_tests() -> bool:
    """Spawn the MCP server and drive the JSON-RPC handshake + a tool call."""
    print("=== MCP stdio round-trip test ===\n")

    if not os.path.exists(SERVER_PATH):
        print(f"SKIP: {SERVER_PATH} not found (run from the repo root)")
        return True

    env = os.environ.copy()
    # validate_answer stub doesn't need a real key, but the LLMWrapper
    # constructor at import time checks for one. Set a dummy to let the
    # module finish importing.
    env.setdefault("OPENROUTER_API_KEY", "dummy-key-for-mcp-stdio-test")
    # Default log level ERROR keeps stdout clean of non-RPC noise.
    env.setdefault("STRONGCHAT_LOG_LEVEL", "ERROR")

    proc = subprocess.Popen(
        [PYTHON, SERVER_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=os.getcwd(),
    )

    try:
        # 1. initialize
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "stdio-test", "version": "1.0"},
            },
        })
        init_resp = _expect_response_matching_id(proc, 1, timeout=10.0)
        assert "result" in init_resp, f"initialize failed: {init_resp}"
        result = init_resp["result"]
        assert "protocolVersion" in result, f"no protocolVersion: {result}"
        assert "capabilities" in result, f"no capabilities: {result}"
        print(f"1. initialize OK: protocolVersion={result['protocolVersion']}")

        # 2. notifications/initialized (no response expected)
        _send(proc, {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })

        # 3. tools/list -> both tools present
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        list_resp = _expect_response_matching_id(proc, 2, timeout=5.0)
        assert "result" in list_resp, f"tools/list failed: {list_resp}"
        tools = list_resp["result"]["tools"]
        tool_names = {t["name"] for t in tools}
        assert "retrieve_context" in tool_names, (
            f"retrieve_context missing from tools/list: {tool_names}"
        )
        assert "validate_answer" in tool_names, (
            f"validate_answer missing from tools/list: {tool_names}"
        )
        print(f"2. tools/list OK: {sorted(tool_names)}")

        # find the validate_answer tool description to confirm contract text
        v_tool = next(t for t in tools if t["name"] == "validate_answer")
        assert "NOT IMPLEMENTED" in v_tool["description"], (
            f"validate_answer description missing NOT IMPLEMENTED marker: "
            f"{v_tool['description']!r}"
        )

        # 4. tools/call validate_answer -> the stub raises
        # NotImplementedError, which MCPServer surfaces either as
        # isError=true on the CallToolResult OR as a JSON-RPC error.
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "validate_answer",
                "arguments": {
                    "answer": "synthesized answer",
                    "context": {"correlation_id": "x", "traces": []},
                },
            },
        })
        call_resp = _expect_response_matching_id(proc, 3, timeout=10.0)

        # Accept either: isError=true on the CallToolResult, OR a
        # JSON-RPC error object. Both are proof the tool actually ran
        # end-to-end through the stdio transport.
        if "error" in call_resp:
            err = call_resp["error"]
            msg_text = str(err.get("data", "")) + " " + str(err.get("message", ""))
            assert "NotImplementedError" in msg_text or "validate_answer" in msg_text, (
                f"validate_answer error didn't carry the contract text: {err}"
            )
            print(f"3. tools/call validate_answer OK (JSON-RPC error): "
                  f"code={err.get('code')}")
        elif "result" in call_resp:
            result_obj = call_resp["result"]
            assert result_obj.get("isError") in (True, "true", 1, "1"), (
                f"validate_answer call did not surface as an error: {result_obj}"
            )
            # content is a list of {type, text} blocks; concatenate text.
            content = result_obj.get("content", [])
            text = " ".join(
                block.get("text", "") for block in content
                if isinstance(block, dict)
            )
            assert "NotImplementedError" in text or "validate_answer" in text or "valid" in text, (
                f"validate_answer error content missing contract text: {text!r}"
            )
            print(f"3. tools/call validate_answer OK (isError=true): "
                  f"{text[:120]}...")
        else:
            raise AssertionError(
                f"validate_answer call returned neither result nor error: {call_resp}"
            )

        print("\n=== Result ===")
        print("PASS")
        return True

    except AssertionError as exc:
        print(f"FAIL: {exc}")
        # Dump any stderr the server emitted for debugging.
        if proc.stderr is not None:
            try:
                err_bytes = proc.stderr.read()
                if err_bytes:
                    print("--- server stderr (truncated) ---")
                    print(err_bytes.decode("utf-8", "replace")[:2000])
            except Exception:
                pass
        return False
    except Exception as exc:
        print(f"ERROR: {exc}")
        return False
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    success = asyncio.run(run_tests())
    sys.exit(0 if success else 1)