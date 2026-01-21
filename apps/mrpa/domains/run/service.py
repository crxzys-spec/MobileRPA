import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import HTTPException

from ...constants import ROOT_DIR
from ...api.schemas import RunRequest

RUN_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
STEP_ID_RE = RUN_ID_RE


def _validate_run_id(run_id: str) -> str:
    if not RUN_ID_RE.match(run_id):
        raise HTTPException(status_code=400, detail="invalid run id")
    return run_id


def _validate_step_id(step_id: str) -> str:
    if not STEP_ID_RE.match(step_id):
        raise HTTPException(status_code=400, detail="invalid step id")
    return step_id


def _validate_run_request(payload: RunRequest) -> None:
    if payload.plan_verify not in ("llm", "none"):
        raise HTTPException(status_code=400, detail="invalid plan_verify value")
    if payload.max_steps <= 0:
        raise HTTPException(status_code=400, detail="max_steps must be positive")
    if payload.plan_max_steps <= 0:
        raise HTTPException(
            status_code=400, detail="plan_max_steps must be positive"
        )


def _is_pid_running(pid: int) -> bool:
    if pid is None:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", "PID eq {}".format(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return False
        output = result.stdout or ""
        return re.search(r"\b{}\b".format(pid), output) is not None
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int) -> None:
    if pid is None:
        return
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return
    try:
        os.kill(pid, 15)
    except OSError:
        return


def _find_pid_by_hint(hint: str) -> Optional[int]:
    if os.name != "nt":
        return None
    if not hint:
        return None
    command = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*" + hint + "*' } | "
        "Select-Object -ExpandProperty ProcessId"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        timeout=8,
    )
    if result.returncode != 0:
        return None
    for line in (result.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            return int(line)
        except ValueError:
            continue
    return None


def _read_json(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_text(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_log_tail(path: Path, limit: int) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    limit = max(1, min(int(limit), 2000))
    total_lines = 0
    tail = deque(maxlen=limit)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                total_lines += 1
                tail.append(line)
    except OSError:
        return None
    lines = list(tail)
    return {
        "text": "".join(lines),
        "lines": len(lines),
        "total_lines": total_lines,
        "truncated": total_lines > len(lines),
        "updated_time": path.stat().st_mtime,
        "log_path": str(path),
    }


def _skip_lines(handle, count: int) -> int:
    skipped = 0
    while skipped < count:
        line = handle.readline()
        if not line:
            break
        skipped += 1
    return skipped


async def _stream_log_lines(
    path: Path,
    start_line: int,
    interval: float,
    batch_lines: int,
) -> AsyncGenerator[Dict[str, object], None]:
    start_line = max(0, int(start_line))
    batch_lines = max(1, min(int(batch_lines), 200))
    interval = max(0.1, min(float(interval), 5.0))

    line_no = 0
    reset_needed = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        skipped = _skip_lines(handle, start_line)
        line_no = skipped
        if skipped < start_line:
            handle.seek(0)
            line_no = 0
            reset_needed = True

        buffer: List[str] = []
        buffer_start = line_no + 1
        while True:
            line = handle.readline()
            if line:
                if not buffer:
                    buffer_start = line_no + 1
                buffer.append(line)
                line_no += 1
                if len(buffer) >= batch_lines:
                    yield {
                        "text": "".join(buffer),
                        "line_start": buffer_start,
                        "line_end": line_no,
                        "total_lines": line_no,
                        "reset": reset_needed,
                    }
                    reset_needed = False
                    buffer = []
            else:
                if buffer:
                    yield {
                        "text": "".join(buffer),
                        "line_start": buffer_start,
                        "line_end": line_no,
                        "total_lines": line_no,
                        "reset": reset_needed,
                    }
                    reset_needed = False
                    buffer = []
                try:
                    if path.exists() and path.stat().st_size < handle.tell():
                        handle.seek(0)
                        line_no = 0
                        reset_needed = True
                except OSError:
                    pass
                await asyncio.sleep(interval)


class RunManager:
    def __init__(self, outputs_dir: Path) -> None:
        self._outputs_dir = outputs_dir
        self._lock = threading.Lock()
        self._processes: Dict[str, subprocess.Popen] = {}

    def start_run(self, request: RunRequest) -> Dict[str, object]:
        run_id = self._new_run_id()
        run_dir = self._outputs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        output_path = run_dir / "result.json"
        log_path = run_dir / "run.log"

        cmd = self._build_command(request, run_dir, output_path)
        metadata = {
            "id": run_id,
            "goal": request.goal,
            "device_id": request.device,
            "status": "running",
            "start_time": time.time(),
            "command": cmd,
            "trace_dir": str(run_dir),
            "output_path": str(output_path),
            "log_path": str(log_path),
        }
        self._write_run_metadata(run_dir, metadata)

        log_file = open(log_path, "w", encoding="utf-8")
        process = subprocess.Popen(
            cmd,
            cwd=str(ROOT_DIR),
            stdout=log_file,
            stderr=log_file,
            text=True,
        )
        metadata["pid"] = process.pid
        self._write_run_metadata(run_dir, metadata)
        with self._lock:
            self._processes[run_id] = process
        thread = threading.Thread(
            target=self._watch_run,
            args=(run_id, run_dir, process, log_file),
            daemon=True,
        )
        thread.start()
        return metadata

    def stop_run(self, run_id: str) -> Dict[str, object]:
        run_id = _validate_run_id(run_id)
        with self._lock:
            process = self._processes.get(run_id)
        run_dir = self._outputs_dir / run_id
        metadata = _read_json(run_dir / "run.json") or {"id": run_id}
        if not process:
            pid = metadata.get("pid")
            if not pid:
                pid = _find_pid_by_hint(run_id)
            if not pid:
                raise HTTPException(status_code=404, detail="run not active")
            _terminate_pid(pid)
            metadata["pid"] = pid
        else:
            _terminate_process(process)
            metadata["pid"] = process.pid
        metadata["status"] = "stopping"
        metadata["stop_requested"] = time.time()
        self._write_run_metadata(run_dir, metadata)
        return {"id": run_id, "status": "stopping"}

    def list_runs(self) -> List[Dict[str, object]]:
        if not self._outputs_dir.exists():
            return []
        runs = []
        for item in sorted(
            self._outputs_dir.iterdir(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        ):
            if not item.is_dir():
                continue
            run_id = item.name
            if not RUN_ID_RE.match(run_id):
                continue
            metadata = _read_json(item / "run.json") or {}
            metadata.setdefault("id", run_id)
            metadata.setdefault("trace_dir", str(item))
            metadata["updated_time"] = item.stat().st_mtime
            with self._lock:
                process = self._processes.get(run_id)
            dirty = False
            if process and metadata.get("status") == "running":
                metadata["pid"] = process.pid
                dirty = True
            pid = metadata.get("pid")
            status = (metadata.get("status") or "").lower()
            if pid and status in ("running", "stopping") and not _is_pid_running(pid):
                metadata["status"] = "stopped"
                metadata.setdefault("end_time", time.time())
                metadata.setdefault("exit_code", -1)
                dirty = True
            if dirty:
                self._write_run_metadata(item, metadata)
            runs.append(metadata)
        return runs

    def _build_command(
        self, request: RunRequest, run_dir: Path, output_path: Path
    ) -> List[str]:
        cmd = [
            sys.executable,
            str(ROOT_DIR / "bot.py"),
        ]
        if request.device:
            cmd.extend(["--device", request.device])
        cmd.extend(
            [
                "agent",
                "--goal",
                request.goal,
                "--max-steps",
                str(request.max_steps),
                "--max-actions",
                str(request.max_actions),
                "--trace-dir",
                str(run_dir),
                "--output",
                str(output_path),
            ]
        )
        if request.execute:
            cmd.append("--execute")
        if request.text_only:
            cmd.append("--text-only")
        if request.decision_mode:
            cmd.extend(["--decision-mode", request.decision_mode])
        if request.plan:
            cmd.append("--plan")
        cmd.extend(["--plan-max-steps", str(request.plan_max_steps)])
        cmd.extend(["--plan-verify", request.plan_verify])
        if not request.plan_resume:
            cmd.append("--no-plan-resume")
        if request.skills:
            cmd.append("--skills")
        if request.skills_only:
            cmd.append("--skills-only")
        return cmd

    def _new_run_id(self) -> str:
        base = time.strftime("run_%Y%m%d_%H%M%S")
        run_id = base
        index = 1
        while (self._outputs_dir / run_id).exists():
            index += 1
            run_id = "{}_{}".format(base, index)
        return run_id

    def _write_run_metadata(self, run_dir: Path, metadata: Dict[str, object]) -> None:
        (run_dir / "run.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _watch_run(
        self,
        run_id: str,
        run_dir: Path,
        process: subprocess.Popen,
        log_file,
    ) -> None:
        exit_code = process.wait()
        log_file.close()
        metadata = _read_json(run_dir / "run.json") or {}
        metadata["end_time"] = time.time()
        metadata["exit_code"] = exit_code
        metadata["status"] = "finished" if exit_code == 0 else "failed"
        self._write_run_metadata(run_dir, metadata)
        with self._lock:
            self._processes.pop(run_id, None)


def _terminate_process(process: Optional[subprocess.Popen]) -> None:
    if not process:
        return
    try:
        process.terminate()
    except OSError:
        pass


def _list_steps(run_dir: Path) -> List[Dict[str, object]]:
    steps = []
    for step_dir in sorted(run_dir.glob("step_*")):
        if not step_dir.is_dir():
            continue
        step_id = step_dir.name
        decision = _read_json(step_dir / "decision.json") or {}
        steps.append(
            {
                "id": step_id,
                "decision": decision,
                "has_screen": (step_dir / "screen.png").exists(),
                "updated_time": step_dir.stat().st_mtime,
            }
        )
    return steps


def _step_payload(run_id: str, step_id: str, step_dir: Path) -> Dict[str, object]:
    return {
        "run_id": run_id,
        "step_id": step_id,
        "decision": _read_json(step_dir / "decision.json"),
        "prompt": _read_text(step_dir / "prompt.txt"),
        "response": _read_text(step_dir / "response.txt"),
        "context": _read_json(step_dir / "context.json"),
        "ocr_payload": _read_json(step_dir / "ocr_payload.json"),
        "verification": _read_json(step_dir / "verification.json"),
        "screen_url": "/outputs/{}/{}".format(run_id, "screen.png"),
        "step_screen_url": "/outputs/{}/{}".format(run_id, "{}/screen.png".format(step_id)),
        "step_after_url": "/outputs/{}/{}".format(run_id, "{}/screen_after.png".format(step_id)),
    }


class RunService:
    def __init__(self, outputs_dir: Path) -> None:
        self._outputs_dir = outputs_dir
        self._manager = RunManager(outputs_dir)

    def _get_run_dir(self, run_id: str) -> Path:
        run_id = _validate_run_id(run_id)
        run_dir = self._outputs_dir / run_id
        if not run_dir.exists():
            raise HTTPException(status_code=404, detail="run not found")
        return run_dir

    def get_run_log_path(self, run_id: str) -> Path:
        run_dir = self._get_run_dir(run_id)
        log_path = run_dir / "run.log"
        if not log_path.exists():
            raise HTTPException(status_code=404, detail="log not found")
        return log_path

    def list_runs(self) -> List[Dict[str, object]]:
        return self._manager.list_runs()

    def get_run(self, run_id: str) -> Dict[str, object]:
        run_dir = self._get_run_dir(run_id)
        metadata = _read_json(run_dir / "run.json") or {"id": run_id}
        metadata["steps"] = _list_steps(run_dir)
        metadata["updated_time"] = run_dir.stat().st_mtime
        return metadata

    def get_step(self, run_id: str, step_id: str) -> Dict[str, object]:
        run_id = _validate_run_id(run_id)
        _validate_step_id(step_id)
        step_dir = self._outputs_dir / run_id / step_id
        if not step_dir.exists():
            raise HTTPException(status_code=404, detail="step not found")
        return _step_payload(run_id, step_id, step_dir)

    def get_run_log(self, run_id: str, limit: int = 200) -> Dict[str, object]:
        log_path = self.get_run_log_path(run_id)
        payload = _read_log_tail(log_path, limit)
        if payload is None:
            raise HTTPException(status_code=404, detail="log not found")
        payload["run_id"] = run_id
        return payload

    async def stream_run_log(
        self,
        run_id: str,
        start_line: int = 0,
        interval: float = 0.5,
        batch_lines: int = 50,
    ) -> AsyncGenerator[Dict[str, object], None]:
        run_id = _validate_run_id(run_id)
        log_path = self.get_run_log_path(run_id)
        async for payload in _stream_log_lines(
            log_path, start_line, interval, batch_lines
        ):
            payload["run_id"] = run_id
            yield payload

    def start_run(self, payload: RunRequest) -> Dict[str, object]:
        _validate_run_request(payload)
        return self._manager.start_run(payload)

    def stop_run(self, run_id: str) -> Dict[str, object]:
        return self._manager.stop_run(run_id)
