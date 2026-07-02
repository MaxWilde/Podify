# ClassicPod Dashboard

ClassicPod Dashboard is a Linux web app for browsing and managing music on an iPod Classic.
It is built on top of `gpod-utils` for iPod database read/write operations.

Reference: [Original gpod-utils repository](https://github.com/whatdoineed2do/gpod-utils)

## Screenshot

![ClassicPod Dashboard](image.png)

## Features

- Load iPod library from a mountpoint or direct `iTunesDB` path
- Browse tracks, artists, albums, and album art
- Add music files/folders to the iPod
- Auto-convert FLAC to ALAC during import
- Delete tracks or albums from the iPod
- Create/remove playlists
- Add/remove tracks to/from playlists
- Settings menu with Music Directory configuration
- Optional auto-sync of FLAC files from Music Directory (recursive) when loading a connected iPod
- Optional deletion of source files after successful auto-sync

## Run With Docker

1. Mount your iPod on the host.
2. Create a `.env` file in the project root:

```bash
cat > .env <<'EOF'
IPOD_MOUNTPOINT=/media
MUSIC_DIR_HOST=/home/max/Music/deemix Music
HOST_IP=0.0.0.0
HOST_PORT=8080
APP_PORT=8080
EOF
```

3. Start the app:

```bash
sudo docker compose down
sudo docker compose up --build -d --force-recreate
```

4. Open `http://localhost:8080`.
5. Use mountpoint `/ipod` in the UI.
6. In Settings, set Music Directory to `/music`.
7. Enable auto-sync if desired.

Optional custom host IP/port:

```bash
sudo env IPOD_MOUNTPOINT=/media MUSIC_DIR_HOST="/home/you/Music" HOST_IP=0.0.0.0 HOST_PORT=8090 APP_PORT=8080 docker compose up --build -d --force-recreate
```

Example with spaces:

```bash
sudo env IPOD_MOUNTPOINT=/media MUSIC_DIR_HOST="/home/max/Music/deemix Music" docker compose up --build -d --force-recreate
```

## Run Without Docker (Linux)

1. Install system dependencies:

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-pip ffmpeg git autoconf automake build-essential libtool pkg-config libglib2.0-dev libjson-c-dev libsqlite3-dev libgpod-dev libavcodec-dev libavformat-dev libavutil-dev libswresample-dev libswscale-dev
```

2. Install `gpod-utils` from source:

```bash
git clone --depth 1 https://github.com/whatdoineed2do/gpod-utils /tmp/gpod-utils
cd /tmp/gpod-utils
autoreconf --install
./configure
make -j"$(nproc)"
sudo make install
```

3. Install Python dependencies:

```bash
cd /path/to/classicpod_dashboard
python3 -m pip install -r requirements.txt
```

4. Build the playlist helper:

```bash
GPOD_PC=""; for C in gpod-1.0 libgpod libgpod-1.0 gpod; do if pkg-config --exists "$C"; then GPOD_PC="$C"; break; fi; done; if [ -z "$GPOD_PC" ]; then GPOD_PC="$(pkg-config --list-all | awk '{print $1}' | grep -Ei '(^|-)gpod' | head -n1)"; fi; gcc -O2 -Wall -Wextra -std=c11 $(pkg-config --cflags "$GPOD_PC" glib-2.0) -o /usr/local/bin/gpod-playlistctl ./tools/gpod-playlistctl.c $(pkg-config --libs "$GPOD_PC" glib-2.0)
```

5. Run the app:

```bash
python3 app.py
```

6. Open `http://localhost:8080` and use your host iPod mountpoint.
