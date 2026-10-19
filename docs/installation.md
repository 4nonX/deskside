# Installation

deskside runs as one container. It needs a configuration file, a few secret files and a volume for its database.

## Requirements

- Docker with Compose, or Python 3.12+ if you prefer to run it directly.
- Network access from the deskside host to whatever you want to read: SNMP (UDP 161) on your switches, the API of your DHCP server or Netdisco, and so on.
- For the `local-arp` source only: the host must sit in the networks it should sweep, and the container needs host networking.

## Steps

1. Get the code and create a working directory next to it:

   ```sh
   git clone https://github.com/4nonX/deskside.git
   cd deskside
   cp config.example.yaml config.yaml
   mkdir secrets
   ```

2. Create the two secrets deskside needs for itself. The session key signs sign-in cookies; the admin password is used once, to create the first account.

   ```sh
   openssl rand -base64 48 > secrets/secret_key
   openssl rand -base64 18 > secrets/admin_password
   chmod 600 secrets/*
   ```

3. Put the credentials for your data sources into `secrets/` as well (one value per file, for example `secrets/snmp_community`), and describe the sources in `config.yaml`. [sources.md](sources.md) explains each source and how to give it the least access it needs.

4. Start it:

   ```sh
   docker compose up -d --build
   docker compose logs -f deskside
   ```

   On first start the log says `created the initial 'admin' account`. Sign in at `http://<host>:8080` as `admin` with the password from `secrets/admin_password`, then create personal accounts under **Users** and stop using the shared one.

5. Check **Sources**. Every source shows when it last succeeded, how long it took and how many entries it delivered. A source that cannot connect says why.

## Behind a reverse proxy

deskside listens on plain HTTP and expects TLS to be terminated in front of it. Pass the usual `X-Forwarded-*` headers and set `DESKSIDE_TRUSTED_PROXIES` to the proxy's address so deskside sees the real client address and sets secure cookies. The live updates use server-sent events on `/api/stream`; disable response buffering for that path if your proxy buffers by default.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DESKSIDE_CONFIG` | `/config/config.yaml` | Path of the configuration file |
| `DESKSIDE_HOST` | `0.0.0.0` | Listen address |
| `DESKSIDE_PORT` | `8080` | Listen port |
| `DESKSIDE_TRUSTED_PROXIES` | `127.0.0.1` | Proxies whose forwarded headers are trusted, comma-separated |
| `DESKSIDE_LOG_LEVEL` | `INFO` | `DEBUG` shows every source run |
| `DESKSIDE_SECRET_KEY` | | Alternative to `server.secret_key` |
| `DESKSIDE_ADMIN_PASSWORD` | | Alternative to `server.admin_password` |

## Vendor names

deskside can show the manufacturer of a network card ("Konica Minolta", "Yealink") based on the first half of the MAC address. The list comes from the IEEE and is not shipped with deskside. Download it once, and again whenever you like:

```sh
docker compose exec deskside deskside update-oui /data/oui.csv
```

Then set `oui_file: /data/oui.csv` in the configuration and restart. This is the only time deskside talks to the internet, and only when you run the command.

## Running without Docker

```sh
cd backend
python -m venv .venv && . .venv/bin/activate
pip install .
cd ../frontend && npm ci && npm run build && cd ../backend
DESKSIDE_CONFIG=../config.yaml deskside
```

## Updating

Pull the new version, rebuild, restart. The database schema is created on start; until the first stable release, schema changes may require starting with a fresh database. The changelog says so when that is the case.

## Backups

Everything deskside knows that is not collected live (devices, names, notes, users) is in the database file, `/data/deskside.db` by default. Back up that volume. Live data rebuilds itself within one polling interval.
