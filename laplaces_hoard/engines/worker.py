"""A persistent worker process with a hard per-call timeout.

SymPy can hang (some `solve`/`integrate` inputs never return). Rather than
trust a signal-based timeout (unreliable on Windows and inside threads),
each call runs in a separate `multiprocessing` process using the `spawn`
context (the only one available on Windows, so the same code path is
exercised on both platforms). If the call does not answer within the
timeout the process is killed and a fresh one is started for the next
call — the worker "self-heals" instead of wedging the app.

`target` must be a *module-level* function (picklable under spawn):
`target(op: str, payload: dict) -> dict`, raising on error.
"""
from __future__ import annotations

import multiprocessing as mp
from typing import Any, Callable, Optional

_CTX = mp.get_context("spawn")


class WorkerTimeout(RuntimeError):
    pass


class WorkerError(RuntimeError):
    pass


def _loop(target: Callable[[str, dict], dict], conn) -> None:
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg is None:
            return
        op, payload = msg
        try:
            result = target(op, payload)
            conn.send(("ok", result))
        except Exception as exc:  # noqa: BLE001 - report any failure to the parent
            conn.send(("error", f"{type(exc).__name__}: {exc}"))


class TimeoutWorker:
    """Restartable process pool of size 1, guarded by a hard timeout."""

    def __init__(self, target: Callable[[str, dict], dict], timeout: float = 10.0):
        self._target = target
        self._timeout = timeout
        self._proc: Optional[mp.process.BaseProcess] = None
        self._parent_conn = None

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.is_alive():
            return
        parent_conn, child_conn = _CTX.Pipe()
        proc = _CTX.Process(target=_loop, args=(self._target, child_conn), daemon=True)
        proc.start()
        self._proc = proc
        self._parent_conn = parent_conn

    def _kill(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.join(timeout=2)
                if self._proc.is_alive():
                    self._proc.kill()
                    self._proc.join(timeout=2)
            except Exception:  # noqa: BLE001
                pass
        self._proc = None
        self._parent_conn = None

    def run(self, op: str, payload: dict, timeout: Optional[float] = None) -> dict[str, Any]:
        timeout = timeout if timeout is not None else self._timeout
        self._ensure_started()
        assert self._parent_conn is not None
        self._parent_conn.send((op, payload))
        if not self._parent_conn.poll(timeout):
            self._kill()
            raise WorkerTimeout(
                f"'{op}' did not finish within {timeout:.0f}s and was stopped; "
                "try a smaller or more specific input"
            )
        try:
            status, value = self._parent_conn.recv()
        except (EOFError, OSError) as exc:
            self._kill()
            raise WorkerError(f"worker died unexpectedly: {exc}") from exc
        if status == "error":
            raise WorkerError(value)
        return value

    def shutdown(self) -> None:
        if self._parent_conn is not None:
            try:
                self._parent_conn.send(None)
            except Exception:  # noqa: BLE001
                pass
        self._kill()
