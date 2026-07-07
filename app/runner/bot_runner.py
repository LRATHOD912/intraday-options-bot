import time
import traceback
from datetime import datetime
import threading
from zoneinfo import ZoneInfo

from app.config import BOT_END_TIME, BOT_LOOP_SECONDS, BOT_START_TIME
from app.execution.live_monitor import monitor_all_open_positions_once
from app.execution.position_manager import get_open_positions
from app.main import run_bot_scan


_runner_thread = None
_stop_event = None
_scan_lock = threading.Lock()
_state_lock = threading.Lock()
_runner_state = {
    "running": False,
    "started_at": None,
    "last_scan_at": None,
    "last_error": None,
    "last_monitor_result": None,
}


def _parse_hhmm(value: str):
    return datetime.strptime(value, "%H:%M").time()


def _within_window(now_et, start_t, end_t):
    return start_t <= now_et.time() <= end_t


def _set_state(**kwargs):
    with _state_lock:
        _runner_state.update(kwargs)


def _run_scan_once_locked():
    try:
        run_bot_scan()
        _set_state(last_scan_at=datetime.now(ZoneInfo("America/New_York")).isoformat(), last_error=None)
        return {"ok": True, "error": None}
    except Exception as exc:
        _set_state(last_error=str(exc))
        print(f"Bot scan error: {exc}")
        traceback.print_exc()
        return {"ok": False, "error": str(exc)}


def run_scan_once():
    with _scan_lock:
        return _run_scan_once_locked()


def _runner_loop(stop_event):
    eastern = ZoneInfo("America/New_York")
    loop_seconds = max(int(BOT_LOOP_SECONDS), 1)
    start_t = _parse_hhmm(BOT_START_TIME)
    end_t = _parse_hhmm(BOT_END_TIME)

    print(
        f"Bot runner started. Window={BOT_START_TIME}-{BOT_END_TIME} ET, "
        f"loop={loop_seconds}s"
    )

    while not stop_event.is_set():
        open_positions = get_open_positions()
        if open_positions:
            monitor_result = monitor_all_open_positions_once()
            _set_state(last_monitor_result=monitor_result)

        now_et = datetime.now(eastern)
        if not _within_window(now_et, start_t, end_t):
            print("Bot idle: outside configured strategy window")
            stop_event.wait(loop_seconds)
            continue

        print("Bot scan running...")
        with _scan_lock:
            _run_scan_once_locked()

        stop_event.wait(loop_seconds)

    _set_state(running=False)


def start_runner():
    global _runner_thread, _stop_event

    if _runner_thread is not None and _runner_thread.is_alive():
        return {"started": False, "message": "Runner already running"}

    _stop_event = threading.Event()
    _runner_thread = threading.Thread(target=_runner_loop, args=(_stop_event,), daemon=True)
    _set_state(
        running=True,
        started_at=datetime.now(ZoneInfo("America/New_York")).isoformat(),
        last_error=None,
    )
    _runner_thread.start()
    return {"started": True, "message": "Runner started"}


def stop_runner(timeout_seconds: int = 10):
    global _runner_thread, _stop_event

    if _runner_thread is None or not _runner_thread.is_alive():
        _set_state(running=False)
        return {"stopped": False, "message": "Runner not running"}

    _stop_event.set()
    _runner_thread.join(timeout=timeout_seconds)
    running = _runner_thread.is_alive()
    _set_state(running=running)
    if not running:
        _runner_thread = None
        _stop_event = None
        return {"stopped": True, "message": "Runner stopped"}

    return {"stopped": False, "message": "Runner stop timed out"}


def get_runner_status():
    with _state_lock:
        state = dict(_runner_state)
    state["thread_alive"] = bool(_runner_thread and _runner_thread.is_alive())
    return state


def run_loop():
    result = start_runner()
    print(result["message"])
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_result = stop_runner()
        print(stop_result["message"])


if __name__ == "__main__":
    run_loop()
