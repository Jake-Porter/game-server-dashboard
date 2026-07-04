# game-server-dashboard

A small self-hosted dashboard for starting, stopping, and viewing logs for
game servers on a home network, without SSHing in every time.

## Architecture

1. **`mc-agent`** (`mc-agent/`) — a FastAPI service that runs natively on the
   game server host. It's the only thing allowed to run `systemctl
   start`/`stop` on the game server units, via a tightly scoped sudoers rule.
   Exposes a bearer-token-authed REST API.
2. **Dashboard** (`dashboard/`) — a static HTML/JS page served by nginx in a
   Docker container. nginx reverse-proxies `/api/` to the agent server-side
   (so the agent's firewall can be scoped to the dashboard host's IP, not
   opened to every browser that loads the page) and injects the auth token
   via an environment variable — the token never ships to the browser.
3. Each game server runs under an instantiated systemd unit
   (`minecraft@<name>.service`) so it can be controlled cleanly instead of
   being started manually via `java -jar`.

## `mc-agent` setup

```
sudo mkdir -p /opt/mc-agent
# copy main.py, requirements.txt, config.yaml (see config.yaml.example) into /opt/mc-agent
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mcagent  # if it doesn't already exist
sudo usermod -aG systemd-journal mcagent   # read-only journal access, needed for the logs endpoint
cd /opt/mc-agent
sudo -u mcagent python3 -m venv venv
sudo -u mcagent ./venv/bin/pip install -r requirements.txt

# generate a token and install the env file (see mc-agent.env.example)
openssl rand -hex 32
sudo cp mc-agent.env.example /etc/mc-agent.env   # then edit in the real token
sudo chmod 600 /etc/mc-agent.env

sudo cp systemd/minecraft@.service /etc/systemd/system/
sudo cp systemd/mc-agent.service /etc/systemd/system/
sudo cp sudoers.d/mc-agent /etc/sudoers.d/mc-agent
sudo chmod 440 /etc/sudoers.d/mc-agent
sudo visudo -cf /etc/sudoers.d/mc-agent   # validate syntax before trusting it

sudo systemctl daemon-reload
sudo systemctl enable --now mc-agent.service
```

Notes:
- `minecraft@.service` must keep `SuccessExitStatus=143` — Minecraft/Java
  exits with 143 on SIGTERM, and without this systemd reports a clean stop
  as `failed`.
- `mc-agent.service` must NOT set `NoNewPrivileges=true` — that blocks
  `sudo` from escalating, which breaks start/stop entirely.
- The sudoers rule only grants `systemctl start`/`stop` on
  `minecraft@*.service`. `is-active` and `journalctl` need no elevated
  privilege at all — journal read access comes from the `systemd-journal`
  group instead.
- Restrict the agent's port with your firewall to only the dashboard
  host's IP — the whole security model assumes the agent is not reachable
  from arbitrary hosts on the network.

## Dashboard setup

Deploy `dashboard/docker-compose.yml` (edit the `MC_AGENT_HOST`,
`MC_AGENT_PORT`, and `MC_AGENT_TOKEN` values first), with `dashboard/html`
mounted read-only at `/usr/share/nginx/html` and `dashboard/templates`
mounted read-only at `/etc/nginx/templates` (nginx's built-in envsubst
templating renders `MC_AGENT_TOKEN` etc. into the proxy config at
container start — the real token only ever needs to live in the
container's environment, never in a committed file).

## Security notes

- Single shared bearer token, fine for solo/internal use — not designed
  for multi-tenant or public exposure.
- No TLS between dashboard and agent; intended for a trusted internal
  network only.
