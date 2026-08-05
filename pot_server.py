import atexit
import json
import logging
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

logger = logging.getLogger("saving_full_bot.pot")
PING_URL = "http://127.0.0.1:4416/ping"


def _is_ready() -> bool:
    try:
        with urlopen(PING_URL, timeout=0.4) as response:
            data = json.load(response)
        return bool(data.get("version"))
    except Exception:
        return False


def ensure_pot_server(server_home: Path, node_executable: str) -> None:
    if _is_ready():
        logger.info("PO-token server already running")
        return

    script = server_home / "build" / "main.js"
    try:
        script_text = script.read_text(encoding="utf-8")
    except OSError:
        logger.warning("PO-token server build was not found")
        return

    unsafe_hosts = ('host: "::"', 'host: "0.0.0.0"')
    if 'host: "127.0.0.1"' not in script_text or any(
        host in script_text for host in unsafe_hosts
    ):
        logger.warning("PO-token server is not restricted to localhost")
        return

    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [node_executable, str(script)],
        cwd=server_home,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )

    for _ in range(20):
        if _is_ready():
            logger.info("PO-token server started on 127.0.0.1:4416")
            atexit.register(process.terminate)
            return
        if process.poll() is not None:
            break
        time.sleep(0.1)

    if process.poll() is None:
        process.terminate()
    logger.warning("PO-token server failed to start")
