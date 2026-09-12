from __future__ import annotations
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import server
print("[WaterPulse V9.4] server import OK",flush=True)
import uvicorn
uvicorn.run(server.app,host="0.0.0.0",port=int(os.getenv("PORT","8080")),log_level="info")
