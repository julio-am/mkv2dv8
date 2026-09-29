"""Cancellable, shell-free subprocess execution, including native Windows pipes."""
from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from .models import Cancelled, OperationError
from .platform_tools import popen_external


class Runner:
    def __init__(self, cancel: threading.Event | None = None, log: Callable[[str], None] | None = None):
        self.cancel = cancel or threading.Event()
        self.log = log or (lambda text: None)

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled("Cancelled; original file preserved.")

    def _spawn(self, args: list[str], cwd: Path | None = None, stdin=None):
        self.check()
        self.log("$ " + subprocess.list2cmdline([str(x) for x in args]))
        try:
            return popen_external([str(x) for x in args], stdin=stdin if stdin is not None else subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd,
                                  start_new_session=os.name != "nt")
        except OSError as error:
            raise OperationError(f"Cannot start {Path(args[0]).name}: {error}") from error

    @staticmethod
    def _stop(processes) -> None:
        for proc in processes:
            if proc.poll() is None:
                try:
                    if os.name == "nt":
                        proc.terminate()
                    else:
                        os.killpg(proc.pid, signal.SIGTERM)
                except OSError:
                    pass
        deadline = time.monotonic() + 2
        for proc in processes:
            try:
                proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    if os.name == "nt":
                        proc.kill()
                    else:
                        os.killpg(proc.pid, signal.SIGKILL)
                except OSError:
                    pass
                proc.wait()

    def _collect(self, processes, streams, on_line=None, timeout=None):
        events = queue.Queue(maxsize=128)
        buffers = {key: deque() for key, _ in streams}
        sizes = {key: 0 for key, _ in streams}
        unfinished = len(streams)
        readers = []

        def read(key, stream):
            try:
                while data := stream.read1(65536):
                    events.put((key, data))
            finally:
                events.put((key, None))
                stream.close()

        for key, stream in streams:
            thread = threading.Thread(target=read, args=(key, stream), daemon=True)
            thread.start()
            readers.append(thread)
        started = time.monotonic()
        interrupted = None
        while unfinished:
            if interrupted is None and (self.cancel.is_set() or timeout and time.monotonic() - started > timeout):
                interrupted = Cancelled("Cancelled; original file preserved.") if self.cancel.is_set() else OperationError("Tool timed out")
                self._stop(processes)
            try:
                key, data = events.get(timeout=0.1)
            except queue.Empty:
                continue
            if data is None:
                unfinished -= 1
                continue
            buffers[key].append(data)
            sizes[key] += len(data)
            # Tool logs must not consume memory proportional to movie duration.
            while sizes[key] > 16 * 1024 * 1024 and len(buffers[key]) > 1:
                sizes[key] -= len(buffers[key].popleft())
            decoded = data.decode("utf-8", "replace")
            if on_line:
                on_line(decoded)
        for thread in readers:
            thread.join()
        for proc in processes:
            proc.wait()
        if interrupted:
            raise interrupted
        return {key: b"".join(parts).decode("utf-8", "replace") for key, parts in buffers.items()}

    def run(self, args: list[str], *, cwd: Path | None = None, accepted=(0,), on_line=None, timeout=None) -> str:
        proc = self._spawn(args, cwd)
        try:
            result = self._collect([proc], [("stdout", proc.stdout), ("stderr", proc.stderr)], on_line, timeout)
        except BaseException:
            self._stop([proc])
            raise
        self.check()
        if proc.returncode not in accepted:
            raise OperationError(f"{Path(args[0]).name} exited {proc.returncode}:\n{(result['stderr'] or result['stdout'])[-5000:]}")
        if proc.returncode or result["stderr"].strip():
            self.log((result["stderr"] or result["stdout"])[-4000:])
        return result["stdout"]

    def pipe(self, first: list[str], second: list[str], *, cwd: Path | None = None, on_line=None) -> str:
        producer = self._spawn(first, cwd)
        try:
            consumer = self._spawn(second, cwd, producer.stdout)
        except BaseException:
            producer.stdout.close()
            self._stop([producer])
            raise
        producer.stdout.close()
        try:
            results = self._collect([producer, consumer], [("producer", producer.stderr),
                                    ("stdout", consumer.stdout), ("stderr", consumer.stderr)], on_line)
        except BaseException:
            self._stop([producer, consumer])
            raise
        self.check()
        if producer.returncode or consumer.returncode:
            raise OperationError(f"Streaming failed ({producer.returncode}, {consumer.returncode}):\n"
                                 + "\n".join(results.values())[-5000:])
        return results["stdout"]
