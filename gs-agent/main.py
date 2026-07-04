import os
import subprocess

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

CONFIG_PATH = os.environ.get("GS_AGENT_CONFIG", "/opt/gs-agent/config.yaml")
TOKEN = os.environ["GS_AGENT_TOKEN"]
SYSTEMCTL = "/usr/bin/systemctl"
SUDO = "/usr/bin/sudo"
JOURNALCTL = "/usr/bin/journalctl"

with open(CONFIG_PATH) as f:
    CONFIG = yaml.safe_load(f)

SERVERS = {s["name"]: s for s in CONFIG["servers"]}

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization"],
)


def check_auth(authorization: str = Header(None)):
    if authorization != f"Bearer {TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


def require_server(name: str) -> str:
    if name not in SERVERS:
        raise HTTPException(status_code=404, detail="unknown server")
    return SERVERS[name]["unit"]


def is_active(unit: str) -> str:
    result = subprocess.run(
        [SYSTEMCTL, "is-active", unit], capture_output=True, text=True
    )
    return result.stdout.strip()


@app.get("/api/servers", dependencies=[Depends(check_auth)])
def list_servers():
    return [
        {
            "name": name,
            "display_name": cfg.get("display_name", name),
            "status": is_active(cfg["unit"]),
        }
        for name, cfg in SERVERS.items()
    ]


@app.post("/api/servers/{name}/start", dependencies=[Depends(check_auth)])
def start_server(name: str):
    unit = require_server(name)
    result = subprocess.run([SUDO, SYSTEMCTL, "start", unit], capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip())
    return {"name": name, "status": is_active(unit)}


@app.post("/api/servers/{name}/stop", dependencies=[Depends(check_auth)])
def stop_server(name: str):
    unit = require_server(name)
    result = subprocess.run([SUDO, SYSTEMCTL, "stop", unit], capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip())
    return {"name": name, "status": is_active(unit)}


@app.get("/api/servers/{name}/logs", dependencies=[Depends(check_auth)])
def server_logs(name: str, lines: int = 100):
    unit = require_server(name)
    lines = max(1, min(lines, 1000))
    result = subprocess.run(
        [JOURNALCTL, "-u", unit, "-n", str(lines), "--no-pager", "-q"],
        capture_output=True,
        text=True,
    )
    return {"name": name, "logs": result.stdout}
