# TuxPlayer

TuxPlayer laver én permanent MP3-stream fra Twitch, så Music Assistant kun skal kende én fast URL:

`http://192.168.2.124:8766/stream/`

Hvis ingen kanal er valgt, kanalen er offline, eller Streamlink/FFmpeg fejler, leverer TuxPlayer stilhed i stedet for 404. Systemet er bygget til lokal drift med Docker og et enkelt dansk adminpanel.

## Hovedidé

Flowet er:

`Twitch -> Streamlink -> FFmpeg decode -> TuxPlayer PCM/MP3 pipeline -> /stream/ -> Music Assistant`

Der er kun én aktiv Twitch-kilde ad gangen, og alle lyttere deler samme outputstream.

## Funktioner

- Fast endpoint på `/stream/` med `audio/mpeg`
- Stilhed som fallback i stedet for 404
- Én central Streamlink/FFmpeg-pipeline delt af alle lyttere
- Idle-timeout der stopper Twitch-kilden, når ingen lytter med
- SQLite til kanaler og indstillinger i `./data/tuxplayer.db`
- Dansk admin-UI med store knapper
- Volume-slider i UI
- Valgfri Twitch API-status via `TWITCH_CLIENT_ID` og `TWITCH_CLIENT_SECRET`
- Valgfri HTTP Basic Auth for UI og ændrende API-kald

## Krav

- Docker
- Docker Compose
- En host hvor `network_mode: bridge` er tilladt

## Hurtig start

```bash
cd /docker_data/tuxplayer
cp .env.example .env
nano .env
docker compose up -d --build
```

## Adgang

- UI: [http://192.168.2.124:8766](http://192.168.2.124:8766)
- Health: `http://192.168.2.124:8766/health`
- Status API: `http://192.168.2.124:8766/api/status`
- Permanent stream: `http://192.168.2.124:8766/stream/`

## Music Assistant

Tilføj kun denne ene URL:

`http://192.168.2.124:8766/stream/`

Der skal ikke laves én URL pr. DJ.

## Konfiguration

Projektet bruger `.env`. Start med `.env.example`.

Vigtige variabler:

- `TZ=Europe/Copenhagen`
- `PUBLIC_BASE_URL=http://192.168.2.124:8766`
- `STREAM_IDLE_TIMEOUT=30`
- `STREAM_BITRATE=160k`
- `STREAM_SAMPLE_RATE=44100`
- `STREAM_VOLUME=1.8`
- `STREAM_CHUNK_MS=50`
- `SUBSCRIBER_QUEUE_SIZE=24`
- `STREAMLINK_LIVE_EDGE=3`
- `STREAMLINK_QUALITY=best`
- `TWITCH_CLIENT_ID=`
- `TWITCH_CLIENT_SECRET=`
- `ADMIN_USERNAME=`
- `ADMIN_PASSWORD=`
- `LOG_LEVEL=INFO`

## Twitch API credentials

Hvis `TWITCH_CLIENT_ID` og `TWITCH_CLIENT_SECRET` er sat, bruger TuxPlayer Twitch API til live-status, titel, seertal og profilbillede.

Hvis de er tomme, virker systemet stadig, men UI vil typisk vise `ukendt`, indtil afspilning bliver forsøgt eller Streamlink returnerer en fejl.

## Lyd og tuning

Du kan justere lydniveau direkte i UI’et via volume-slideren.

Hvis du vil tune manuelt i `.env`, er de vigtigste:

- `STREAM_VOLUME=1.8` for generelt niveau
- `STREAM_CHUNK_MS=50` for pipeline-chunk størrelse
- `SUBSCRIBER_QUEUE_SIZE=24` for klientbuffer
- `STREAMLINK_LIVE_EDGE=3` for balance mellem stabilitet og latenstid
- `STREAMLINK_QUALITY=best` for kompatibel Twitch-kildevalg

## API-endpoints

- `GET /` adminpanel
- `GET /stream/` permanent MP3-stream
- `GET /stream` redirect til `/stream/`
- `GET /health` healthcheck
- `GET /api/status` status
- `GET /api/channels` liste over kanaler
- `POST /api/channels` opret kanal
- `PUT/PATCH /api/channels/<id>` opdater kanal
- `DELETE /api/channels/<id>` slet kanal
- `POST /api/channels/<id>/select` vælg aktiv kanal
- `POST /api/channels/<id>/favorite` skift favoritstatus
- `POST /api/channels/<id>/test` test kanal
- `POST /api/stream/stop` stop Twitch-kilde
- `POST /api/stream/restart` genstart Twitch-kilde
- `GET /api/logs` seneste logs

## Test

Lokalt:

```bash
pytest
docker compose config
docker compose build
```

Enkle runtime-checks:

```bash
curl http://127.0.0.1:8766/health
curl http://127.0.0.1:8766/api/status
```

## Fejlsøgning

```bash
docker compose ps
docker compose logs -f
docker stats tuxplayer
```

Typiske ting at kontrollere:

- om den valgte Twitch-kanal faktisk er live
- om `streamlink` kan åbne kanalen fra serveren
- om `PUBLIC_BASE_URL` peger på den rigtige host og port
- om der er for aggressiv tuning i `.env`

## Backup

Databasen ligger i:

`./data/tuxplayer.db`

Det er den fil du skal tage backup af, hvis du vil bevare kanaler og indstillinger.

## Opdatering og rebuild

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

## Gitea

Projektet er gjort klar til at blive lagt i Gitea:

- `.env` er ignoreret
- SQLite-filer i `data/` er ignoreret
- lokale Codex/test-filer er ignoreret
- `README.md` er klar som projektforside
- hvis du lægger `banner.png` i `app/static/`, vises det automatisk øverst i UI’et

Eksempel på første push:

```bash
git init
git add .
git commit -m "Initial commit: TuxPlayer"
git branch -M main
git remote add origin https://DIN-GITEA-SERVER/DIG/tuxplayer.git
git push -u origin main
```

Hvis du bruger SSH i stedet:

```bash
git remote add origin git@DIN-GITEA-SERVER:DIG/tuxplayer.git
git push -u origin main
```

## Struktur

```text
tuxplayer/
├── app/
│   ├── static/
│   └── templates/
├── data/
├── tests/
├── .dockerignore
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── README.md
└── requirements.txt
```
