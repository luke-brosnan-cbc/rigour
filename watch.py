"""Limits on agent calls: a subprocess with a wall-clock and an idle watchdog, and a copy filter for big files.

    py watch.py     # selftest
"""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

BIG_MB = 50
SKIP_DIRS = {"_data", "_download", ".venv", "__pycache__", ".pytest_cache", "related"}


def kill_tree(p: subprocess.Popen) -> None:
    """The CLIs start child processes, so kill the whole tree."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True)
    else:
        p.kill()


def run_watched(cmd: list[str], cwd: Path, env: dict, log: Path, minutes: float, idle_minutes: float,
                stdin_text: str | None = None) -> tuple[int | None, str, str, str]:
    """Run cmd and write stdout to `log` as it arrives. Kill it after `minutes`, or after `idle_minutes` with no output.
    Returns (returncode, stdout, stderr, killed), where killed is '', 'timeout' or 'idle'."""
    p = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, encoding="utf-8", errors="replace",
                         stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines: queue.Queue = queue.Queue()

    def pump(stream, tag):
        for line in stream:
            lines.put((tag, line))
        lines.put((tag, None))

    for stream, tag in ((p.stdout, "out"), (p.stderr, "err")):
        threading.Thread(target=pump, args=(stream, tag), daemon=True).start()
    if stdin_text is not None:
        try:
            p.stdin.write(stdin_text)
            p.stdin.close()
        except OSError:  # the process already exited; its output says why
            pass
    out, err, open_streams, killed, killed_at = [], [], 2, "", 0.0
    start = last = time.time()
    with open(log, "w", encoding="utf-8") as f:
        while open_streams:
            try:
                tag, line = lines.get(timeout=1)
            except queue.Empty:
                tag = line = None
            if tag and line is None:
                open_streams -= 1
            elif line is not None:
                last = time.time()
                (out if tag == "out" else err).append(line)
                if tag == "out":
                    f.write(line)
                    f.flush()
            if not killed:
                killed = "timeout" if time.time() - start > 60 * minutes else "idle" if time.time() - last > 60 * idle_minutes else ""
                if killed:
                    killed_at = time.time()
                    kill_tree(p)
            elif time.time() - killed_at > 30:  # a grandchild still holds a pipe open; stop waiting for it
                break
        f.write("\n--- stderr ---\n" + "".join(err))
    try:
        p.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass
    return p.returncode, "".join(out), "".join(err), killed


def skip_big(folder: str, names: list[str]) -> set[str]:
    """shutil.copytree ignore filter: scratch folders, virtual environments and files over BIG_MB."""
    skip = set()
    for n in names:
        path = Path(folder) / n
        if n in SKIP_DIRS or path.is_file() and path.stat().st_size > BIG_MB * 2**20:
            skip.add(n)
    return skip


def _selftest() -> None:
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(dir=Path(__file__).parent))
    try:
        log = tmp / "_test.log"
        code = "import time; print('hello', flush=True); time.sleep(30)"
        t0 = time.time()
        _, out, _, killed = run_watched([sys.executable, "-c", code], tmp, dict(os.environ), log, minutes=1, idle_minutes=0.05)
        assert killed == "idle" and "hello" in out and "hello" in log.read_text(encoding="utf-8"), (killed, out)
        assert time.time() - t0 < 25, "the idle watchdog was too slow"
        rc, out, _, killed = run_watched([sys.executable, "-c", "print(input())"], tmp, dict(os.environ), log, 1, 1, "ok\n")
        assert (rc, out.strip(), killed) == (0, "ok", ""), (rc, out, killed)
        src = tmp / "mvp"
        (src / "_download").mkdir(parents=True)
        (src / "_download" / "x.bin").write_bytes(b"0")
        (src / "big.bin").write_bytes(b"0" * (BIG_MB * 2**20 + 1))
        (src / "app.py").write_text("print(1)\n")
        shutil.copytree(src, tmp / "copy", ignore=skip_big)
        assert sorted(p.name for p in (tmp / "copy").iterdir()) == ["app.py"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("watch.py selftest ok")


if __name__ == "__main__":
    _selftest()
