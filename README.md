# game-server-dashboard

A small self-hosted dashboard for starting, stopping, and viewing logs for
game servers on a home network, without SSHing in every time.

## Architecture

1. **`gs-agent`** (`gs-agent/`) — a FastAPI service that runs natively on the
   game server host. It's the only thing allowed to run `systemctl
   start`/`stop` on the game server units, via a tightly scoped sudoers rule.
   Exposes a bearer-token-authed REST API.
2. **Dashboard** (`dashboard/`) — a static HTML/JS page served by nginx in a
   Docker container. nginx reverse-proxies `/api/` to the agent server-side
   (so the agent's firewall can be scoped to the dashboard host's IP, not
   opened to every browser that loads the page) and injects the auth token
   via an environment variable — the token never ships to the browser.
3. Each game server runs under a systemd unit — instantiated
   (`minecraft@<name>.service`) for Minecraft servers, or a plain
   `<name>.service` for anything else — so it can be controlled cleanly
   instead of being started manually.

## `gs-agent` setup

```
sudo mkdir -p /opt/gs-agent
# copy main.py, requirements.txt, config.yaml (see config.yaml.example) into /opt/gs-agent
sudo useradd --system --no-create-home --home-dir /opt/gs-agent --shell /usr/sbin/nologin gsagent  # if it doesn't already exist
sudo usermod -aG systemd-journal gsagent   # read-only journal access, needed for the logs endpoint
cd /opt/gs-agent
sudo -u gsagent python3 -m venv venv
sudo -u gsagent ./venv/bin/pip install -r requirements.txt

# generate a token and install the env file (see gs-agent.env.example)
openssl rand -hex 32
sudo cp gs-agent.env.example /etc/gs-agent.env   # then edit in the real token
sudo chmod 600 /etc/gs-agent.env

sudo cp systemd/minecraft@.service /etc/systemd/system/
sudo cp systemd/gs-agent.service /etc/systemd/system/
sudo cp sudoers.d/gs-agent /etc/sudoers.d/gs-agent
sudo chmod 440 /etc/sudoers.d/gs-agent
sudo visudo -cf /etc/sudoers.d/gs-agent   # validate syntax before trusting it

sudo systemctl daemon-reload
sudo systemctl enable --now gs-agent.service
```

Notes:
- `minecraft@.service` must keep `SuccessExitStatus=143` — Minecraft/Java
  exits with 143 on SIGTERM, and without this systemd reports a clean stop
  as `failed`. Other games may shut down cleanly on their own (Vintage
  Story does) and don't need this.
- `gs-agent.service` must NOT set `NoNewPrivileges=true` — that blocks
  `sudo` from escalating, which breaks start/stop entirely.
- The sudoers rule only grants `systemctl start`/`stop` on the specific
  units/patterns you list. `is-active` and `journalctl` need no elevated
  privilege at all — journal read access comes from the `systemd-journal`
  group instead.
- Restrict the agent's port with your firewall to only the dashboard
  host's IP — the whole security model assumes the agent is not reachable
  from arbitrary hosts on the network.
- `config.yaml` isn't Minecraft-specific: each entry's `unit` field is
  whatever systemd unit controls that server (`minecraft@<name>.service`
  for instanced Minecraft servers, a plain `<name>.service` for anything
  else — see the Vintage Story entry in `config.yaml.example`). The
  sudoers rule needs a matching `start`/`stop` line for each unit or
  unit pattern you add.
- If you ever rename the agent's system user (or move its install
  directory), rebuild its venv from scratch afterward — venv scripts
  (`pip`, `uvicorn`, etc.) hardcode the old absolute path in their
  shebang lines and will break silently otherwise.
- Different Minecraft versions can require different Java versions.
  Installing a new JDK via `apt` can silently change the *system-wide*
  default `java` (via `update-alternatives`), which will break any
  other server relying on the bare `java` command in its `run.sh`.
  After installing a new JDK: pin the default back with
  `update-alternatives --set java /usr/lib/jvm/<version>/bin/java`,
  and have each server's `run.sh` invoke its required JVM by full path
  (e.g. `/usr/lib/jvm/java-25-openjdk-amd64/bin/java`) rather than the
  bare `java` command, so future JDK installs can't affect it.

## Dashboard setup

Deploy `dashboard/docker-compose.yml` (edit the `GS_AGENT_HOST`,
`GS_AGENT_PORT`, and `GS_AGENT_TOKEN` values first), with `dashboard/html`
mounted read-only at `/usr/share/nginx/html` and `dashboard/templates`
mounted read-only at `/etc/nginx/templates` (nginx's built-in envsubst
templating renders `GS_AGENT_TOKEN` etc. into the proxy config at
container start — the real token only ever needs to live in the
container's environment, never in a committed file). Note this
substitution only happens once at container start, so changing the
template or the env var names requires a full recreate, not just a
reload/restart.

## Security notes

- Single shared bearer token, fine for solo/internal use — not designed
  for multi-tenant or public exposure.
- No TLS between dashboard and agent; intended for a trusted internal
  network only.
