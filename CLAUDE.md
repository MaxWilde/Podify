# Podify – iPod Classic Dashboard (Claude Code Project Spec)

## 1. Overview

**Name:** Podify

Goal: Build a modern React (Vite) single-page web app called **Podify** that acts as a dashboard for an iPod Classic, using the existing Python/Flask backend from the `classicpod_dashboard` repository. The new frontend should:

- Browse the iPod library: tracks, artists, albums, playlists, and album art.
- Perform library operations: add tracks, delete tracks, manage playlists.
- Integrate deemix inside the same Docker container to:
  - Search and download music with configurable quality/format (including FLAC).
  - Move downloaded files into the configured Music Directory.
  - Let the existing auto-sync logic import those files onto the iPod.

Replace the current HTML/templates-based frontend entirely, but **reuse and preserve** the Python backend files (`app.py`, `ipod_service.py`, `settings_service.py`, `album_art.py`, `flac2alac_converter.py`, etc.).

### Backend modification policy

The existing Python backend is known-working and interacts with the iPod Classic's strict database format via `gpod-utils`. **Do not modify backend files unless there is a specific, targeted reason** (e.g., adding a new Flask route for deemix). Never refactor, reorganize, or "clean up" existing backend logic. When a new endpoint is needed, prefer adding it in a new file (e.g., `deemix_service.py`, `deemix_routes.py`) and registering it in `app.py` with a single `app.register_blueprint(...)` call.

---

## 2. Tech Stack

**Backend (already present, to be reused):**

- Python 3 / Flask (`app.py`)
- iPod interaction via `ipod_service.py` and `gpod-*` CLI utilities
- Settings and auto-sync via `settings_service.py`
- Album art via `album_art.py`
- FLAC → ALAC conversion via `flac2alac_converter.py`

**Frontend (new, Podify UI):**

- React 18 + TypeScript
- Vite (React + TypeScript template)
- Tailwind CSS for styling

**Deemix integration (new, same container):**

- `deemix` Python library (installed via pip)
- Thin Python wrapper/service (`deemix_service.py`) exposing deemix functionality
- New Flask Blueprint (`deemix_routes.py`) registered in `app.py`

---

## 3. Repository Layout

```
classicpod_dashboard/
├── app.py                    # existing – minimal changes only
├── ipod_service.py           # existing – do not modify
├── settings_service.py       # existing – do not modify
├── album_art.py              # existing – do not modify
├── flac2alac_converter.py    # existing – do not modify
├── deemix_service.py         # NEW – deemix Python wrapper
├── deemix_routes.py          # NEW – Flask Blueprint for deemix endpoints
├── Dockerfile                # updated
├── docker-compose.yml        # updated if needed
├── requirements.txt          # updated (add deemix)
├── static/                   # kept for album art etc.
├── templates/
│   └── index.html            # updated to serve React dist
├── tools/                    # existing – do not modify
└── frontend/                 # NEW – Podify React/Vite app
    ├── index.html
    ├── vite.config.ts
    ├── tailwind.config.ts
    ├── package.json
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api/              # typed API client functions
        ├── components/       # shared UI components
        ├── pages/            # top-level page components
        └── types/            # shared TypeScript interfaces
```

In production (Docker), the Podify frontend is built and its `dist` is served as static files by Flask. The `/` route in `app.py` is updated to serve `frontend/dist/index.html`.

---

## 4. UI Design – Spotify-Inspired Podify Layout

Podify should visually resemble the Spotify desktop app:

```
┌─────────────────────────────────────────────────────────┐
│  [🔍 Search bar — always visible at top]                │
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│  Left        │  Main content area                       │
│  Sidebar     │  (changes based on sidebar selection)    │
│              │                                          │
│  - Your iPod │                                          │
│  - Library   │                                          │
│    - Albums  │                                          │
│    - Artists │                                          │
│    - Tracks  │                                          │
│    - Playlists│                                         │
│              │                                          │
│  - Deemix    │                                          │
│    Download  │                                          │
│              │                                          │
│  - Upload    │                                          │
│              │                                          │
│  - Settings  │                                          │
│              │                                          │
├──────────────┴──────────────────────────────────────────┤
│  Status bar: iPod device info + connection status       │
└─────────────────────────────────────────────────────────┘
```

### Color scheme

Dark theme, close to Spotify:
- Background: `#121212`
- Sidebar: `#000000`
- Cards/surfaces: `#181818`
- Accent: `#1DB954` (Spotify green) or a neutral white/gray — pick whichever feels cleaner
- Text: `#FFFFFF` (primary), `#B3B3B3` (secondary)

### Sidebar

- Fixed left sidebar (~240px wide).
- Sections:
  - **Your iPod** — device name, model, track count, total duration.
  - **Library** — sub-items: Albums, Artists, Tracks, Playlists.
  - **Deemix** — search/download panel.
  - **Upload** — manual file upload.
  - **Settings** — Podify settings.
- Mountpoint input field at the top of the sidebar (default `/ipod`) with a "Connect" button.

### Search bar

- Persistent top bar.
- In **Library** context: filters the currently viewed library section (tracks/albums/artists).
- In **Deemix** context: triggers a deemix search query.
- Debounce input (300ms) before firing.

### Main content area

- **Albums view:** Grid of album cards (cover art + album name + artist). Click → opens album detail with track list.
- **Artists view:** List or grid of artists. Click → shows albums by that artist.
- **Tracks view:** Table with columns: Title, Artist, Album, Duration, Bitrate. Row actions: Delete, Add to playlist.
- **Playlists view:** List of playlists (name + track count). Click → shows playlist tracks. Actions: Create, Delete, Add/remove tracks.
- **Deemix view:** Search results grid (similar to album/track cards). Download controls per result, including quality selector (FLAC / MP3_320 / MP3_128).
- **Upload view:** Drag-and-drop zone + file picker.
- **Settings view:** Form for all settings.

---

## 5. Existing Backend API – Contract for Podify Frontend

Consume these endpoints exactly as documented. Do not alter their behavior.

### `GET /api/library?mountpoint=<string>`
Returns full library. Response shape:
```json
{
  "mountpoint": "/ipod",
  "device": { "generation": "", "model_name": "", "model_number": "" },
  "track_count": 0,
  "artist_count": 0,
  "album_count": 0,
  "total_duration_seconds": 0.0,
  "playlists": [
    { "name": "", "type": "", "count": 0, "smartpl": false, "track_ids": [] }
  ],
  "tracks": [
    {
      "id": 0,
      "title": "",
      "artist": "",
      "album": "",
      "genre": "",
      "year": 0,
      "playcount": 0,
      "bitrate": 0,
      "size_bytes": 0,
      "duration_seconds": 0.0,
      "ipod_path": "",
      "artwork": false,
      "checksum": ""
    }
  ],
  "auto_sync": { "status": "", "message": "" }
}
```

### `GET /api/cover?mountpoint=<string>&ipod_path=<string>`
Returns image bytes (`image/*`). Use directly as `<img src>` via a blob URL or an API URL.

### `POST /api/delete-tracks`
```json
{ "mountpoint": "/ipod", "ipod_paths": ["/iPod_Control/Music/..."] }
```
Response: `{ "deleted_count": 0, "message": "" }`

### `POST /api/add-tracks`
Multipart form-data: `mountpoint=<string>`, `files=<file[]>`.
Response: `{ "added_count": 0, "converted_count": 0, "conversion_failed_count": 0, "skipped_count": 0, "message": "" }`

### `POST /api/playlists/create`
```json
{ "mountpoint": "/ipod", "playlist_name": "My Playlist" }
```

### `POST /api/playlists/delete`
```json
{ "mountpoint": "/ipod", "playlist_name": "My Playlist" }
```

### `POST /api/playlists/add-tracks`
```json
{ "mountpoint": "/ipod", "playlist_name": "My Playlist", "track_ids": [1, 2, 3] }
```

### `POST /api/playlists/remove-tracks`
```json
{ "mountpoint": "/ipod", "playlist_name": "My Playlist", "track_ids": [1, 2] }
```

### `GET /api/settings`
Returns settings object (at minimum): `music_directory`, `auto_sync_enabled`, `delete_after_sync`.

### `POST /api/settings`
Accepts updated settings object. Returns saved settings.

**Error handling:** All endpoints may return `{ "error": "<message>" }` with a 4xx/5xx status. The Podify frontend must display these errors clearly (toast or inline).

---

## 6. New Backend – Deemix Integration

All deemix logic lives in two new files: `deemix_service.py` and `deemix_routes.py`. Register the blueprint in `app.py`:

```python
# In app.py — only addition needed:
from deemix_routes import deemix_bp
app.register_blueprint(deemix_bp)
```

### `deemix_service.py`

Wraps the `deemix` Python library. Responsibilities:
- Initialize deemix with a configurable download directory and ARL token.
- Expose functions: `search(query, result_type)`, `download(items, quality)`.
- Handle deemix errors and translate them to plain Python exceptions.

### `deemix_routes.py`

Flask Blueprint with prefix `/api/deemix`.

---

#### `GET /api/deemix/config`
Returns:
```json
{
  "enabled": true,
  "arl_configured": true,
  "download_dir": "/music/deemix",
  "music_directory": "/music",
  "default_quality": "FLAC"
}
```

---

#### `POST /api/deemix/config`
Accepts:
```json
{
  "arl": "<deezer-arl-token>",
  "download_subdir": "deemix",
  "default_quality": "FLAC"
}
```
- Validates that `music_directory` from settings exists.
- Creates `download_subdir` inside `music_directory` if it doesn't exist.
- Persists config (alongside existing settings, or in a separate `deemix_config.json`).

---

#### `GET /api/deemix/search?q=<string>&type=<track|album|playlist>`
- Calls deemix search.
- `type` defaults to `track` if omitted.
- Returns:
```json
{
  "results": [
    {
      "deemix_id": "123456",
      "type": "track",
      "title": "Song Title",
      "artist": "Artist Name",
      "album": "Album Name",
      "duration_seconds": 210,
      "cover_url": "https://..."
    }
  ]
}
```

---

#### `POST /api/deemix/download`
Starts one or more downloads. Accepts:
```json
{
  "items": [
    { "id": "123456", "type": "track" },
    { "id": "789", "type": "album" }
  ],
  "quality": "FLAC"
}
```

**Quality options** (map to deemix `TrackFormats`):
| Value | Description |
|-------|-------------|
| `FLAC` | Lossless FLAC (best quality, ~30 MB/track) |
| `MP3_320` | MP3 320 kbps |
| `MP3_128` | MP3 128 kbps |

- `quality` defaults to `FLAC` if omitted.
- Files are saved into the configured `download_dir` (inside `music_directory`).
- Returns:
```json
{
  "requested_count": 2,
  "downloaded_count": 2,
  "failed_count": 0,
  "failures": [],
  "message": "Downloaded 2 item(s) to /music/deemix."
}
```

**Important:** FLAC files downloaded here will be picked up by the existing auto-sync mechanism (which already converts FLAC → ALAC before adding to the iPod). This is the intended pipeline:

```
Deemix download (FLAC) → /music/deemix → auto-sync scans /music → FLAC→ALAC → gpod-cp → iPod
```

---

#### `POST /api/deemix/trigger-sync`
Manually triggers the existing auto-sync logic for a given mountpoint.
```json
{ "mountpoint": "/ipod" }
```
Internally calls `_run_auto_sync_if_enabled(mountpoint)` from `app.py` (extract to a shared helper if needed — this is the only acceptable targeted change to `app.py` beyond blueprint registration).

Response mirrors the `auto_sync` payload from `/api/library`:
```json
{
  "status": "synced",
  "added_count": 5,
  "deleted_source_count": 0,
  "scanned_count": 5,
  "message": "Auto-sync added 5 file(s) from Music Directory."
}
```

---

## 7. Deemix Authentication

- Deemix requires a Deezer ARL token to download.
- The ARL is stored server-side only (never exposed to the frontend beyond a boolean `arl_configured: true/false`).
- The Podify Settings panel should have a field: "Deezer ARL Token" (password input, write-only from the UI — once saved, the UI only shows whether it is configured, not the value).
- Store the ARL in `deemix_config.json` (or alongside settings). Never log it.

---

## 8. Frontend – API Client (`frontend/src/api/`)

Create typed functions for all endpoints. Example structure:

```
api/
  library.ts       # getLibrary, getCoverUrl
  tracks.ts        # deleteTracks, addTracksUpload
  playlists.ts     # createPlaylist, deletePlaylist, addTracksToPlaylist, removeTracksFromPlaylist
  settings.ts      # getSettings, saveSettings
  deemix.ts        # getDeemixConfig, saveDeemixConfig, searchDeemix, downloadDeemix, triggerDeemixSync
```

- Use `fetch` (no extra HTTP library needed).
- All functions return typed promises and throw on non-2xx responses with the `error` message from the response body.
- Use React Query (`@tanstack/react-query`) for data fetching, caching, and loading/error states.

---

## 9. Frontend – State & Routing

- Use React Router v6 for navigation between sections.
- Routes:
  - `/` → redirect to `/library/albums`
  - `/library/albums`
  - `/library/artists`
  - `/library/tracks`
  - `/library/playlists`
  - `/deemix`
  - `/upload`
  - `/settings`
- The `mountpoint` is global state (React context or Zustand store). All API calls read it from there.
- Library data is fetched once per "Connect" action and cached via React Query. Mutations (delete, add, playlist changes) invalidate the library cache and trigger a re-fetch.

---

## 10. Serving the Podify React App via Flask

### Development

- Flask runs on port `8080`.
- Vite dev server runs on port `5173` inside `frontend/`.
- Configure `vite.config.ts` to proxy `/api/*` to `http://localhost:8080`.
- CORS: enable Flask-CORS for development only (guard with `DEBUG` env var).

### Production (Docker)

1. In `Dockerfile`:
   - Install Node.js (LTS).
   - `cd frontend && npm install && npm run build` — outputs to `frontend/dist`.
   - Copy `frontend/dist` to `/app/frontend/dist` inside the container.

2. In `app.py` (targeted change — update the `/` route only):
   ```python
   @app.route("/", defaults={"path": ""})
   @app.route("/<path:path>")
   def serve_react(path):
       dist = os.path.join(app.root_path, "frontend", "dist")
       if path and os.path.exists(os.path.join(dist, path)):
           return send_from_directory(dist, path)
       return send_from_directory(dist, "index.html")
   ```
   This replaces the existing `index()` route.

---

## 11. Docker & Environment

### Environment Variables (existing, unchanged)

| Variable | Description |
|----------|-------------|
| `IPOD_MOUNTPOINT` | Host path to iPod mount (e.g. `/media`) |
| `MUSIC_DIR_HOST` | Host path to Music Directory |
| `HOST_IP` | Bind IP (default `0.0.0.0`) |
| `HOST_PORT` | Host port (default `8080`) |
| `APP_PORT` | Container port (default `8080`) |

### New Environment Variables

| Variable | Description |
|----------|-------------|
| `DEEMIX_DOWNLOAD_SUBDIR` | Subfolder inside `/music` for deemix downloads (default: `deemix`) |

### Dockerfile additions

```dockerfile
# Node.js for building frontend
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs

# Build Podify frontend
COPY frontend /app/frontend
RUN cd /app/frontend && npm install && npm run build

# deemix installed via requirements.txt
```

### docker-compose volumes (unchanged)

- `/media` → iPod mountpoint
- `MUSIC_DIR_HOST` → `/music` (deemix writes to `/music/deemix` by default)

---

## 12. Non-Goals & Constraints

- **Do not** modify `ipod_service.py`, `settings_service.py`, `album_art.py`, or `flac2alac_converter.py` unless there is a concrete, specific bug that must be fixed to make the new feature work. Document any such change with a comment.
- **Do not** refactor or reorganize existing Python code for style reasons.
- No authentication required (local-only use).
- No audio playback in the browser (out of scope).
- Do not expose the ARL token to the frontend.

---

## 13. Implementation Order

1. **Read and understand** `README.md`, `app.py`, `ipod_service.py`, `settings_service.py`.
2. **Set up Podify frontend scaffold:**
   - `cd frontend && npm create vite@latest . -- --template react-ts`
   - Install Tailwind CSS, React Router v6, React Query.
3. **Build the Podify shell UI:**
   - Sidebar, top search bar, main content area, dark theme.
   - Routing between sections.
4. **Wire up existing library APIs:**
   - API client functions.
   - Library views: Albums, Artists, Tracks, Playlists.
   - Album art display.
   - Delete tracks, manage playlists.
5. **Build Upload panel** using `/api/add-tracks`.
6. **Implement deemix backend:**
   - `deemix_service.py` — wrap deemix library.
   - `deemix_routes.py` — Flask Blueprint.
   - Register blueprint in `app.py`.
7. **Build Deemix UI panel in Podify:**
   - Search, results, quality selector, download button, status.
   - Sync-to-iPod button.
8. **Build Settings panel** (existing + ARL token field).
9. **Update Dockerfile** to build Podify frontend and install deemix.
10. **End-to-end test:**
    - Connect to iPod → browse library → delete a track → add a file.
    - Deemix: search → download FLAC → trigger sync → verify track appears in library.
