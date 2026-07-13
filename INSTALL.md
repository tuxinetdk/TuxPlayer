# TuxPlayer Installation

This guide is intended for people who want the fastest path to a working TuxPlayer instance on a Linux host with Docker already installed.

## What You Need

- A Linux machine with Docker and Docker Compose available
- Port `8766` available on the host
- The TuxPlayer project files on disk
- Optional Twitch API credentials
- Optional admin username and password

## Recommended Path

Use the interactive installer:

```bash
chmod +x install.sh
./install.sh
```

The installer will:

- create `.env` from your answers
- preserve `.env.example`
- create the `data/` directory if needed
- optionally run `docker compose up -d --build`

## Manual Installation

If you prefer to configure everything manually:

```bash
cp .env.example .env
nano .env
docker compose up -d --build
```

## Questions the Installer Will Ask

- Server IP or hostname
- Public base URL
- Timezone
- Stream idle timeout
- Stream bitrate
- Stream sample rate
- Default stream volume
- Twitch Client ID
- Twitch Client Secret
- Admin username
- Admin password
- Whether Docker should build and start the stack immediately

## After Installation

Open:

- UI: `http://SERVER_IP:8766`
- Health: `http://SERVER_IP:8766/health`
- Stream: `http://SERVER_IP:8766/stream/`

Add this URL to Music Assistant:

`http://SERVER_IP:8766/stream/`

## Updating

To rebuild after updates:

```bash
docker compose down
docker compose up -d --build
```

## Troubleshooting

Check service status:

```bash
docker compose ps
docker compose logs -f
docker stats tuxplayer
```

If the UI loads but Twitch status stays offline:

- confirm the channel is actually live
- confirm the server can reach Twitch
- confirm your Twitch API credentials are correct if you use them
- confirm `PUBLIC_BASE_URL` matches the real host IP or hostname

## Security Notes

- TuxPlayer is meant for a trusted local network by default.
- Do not expose port `8766` directly to the public internet.
- Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` if other people can reach the UI.
- Use HTTPS and a reverse proxy if external access is required.
