from __future__ import annotations
import json, uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
from .paths import LOG_DIR

LOG_FILE = LOG_DIR / 'agent_runs.jsonl'

def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')

def new_run_id():
    return uuid.uuid4().hex[:12]

def _json_default(x):
    try:
        return x.item()
    except Exception:
        return str(x)

def log_event(event: Dict[str, Any]) -> str:
    event = dict(event)
    event.setdefault('timestamp', now_iso())
    event.setdefault('run_id', new_run_id())
    with LOG_FILE.open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False, default=_json_default) + '\n')
    return event['run_id']

def read_logs(limit=200):
    if not LOG_FILE.exists():
        return []
    lines = LOG_FILE.read_text(encoding='utf-8').splitlines()[-limit:]
    out=[]
    for line in lines:
        try: out.append(json.loads(line))
        except Exception: pass
    return out
