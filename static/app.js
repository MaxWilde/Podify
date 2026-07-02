const form = document.getElementById("mount-form");
const mountpointInput = document.getElementById("mountpoint");
const loadButton = document.getElementById("load-button");
const addForm = document.getElementById("add-form");
const musicFilesInput = document.getElementById("music-files");
const musicFolderInput = document.getElementById("music-folder");
const musicSourceMode = document.getElementById("music-source-mode");
const selectMusicButton = document.getElementById("select-music-button");
const clearSelectionButton = document.getElementById("clear-selection-button");
const selectionSummary = document.getElementById("selection-summary");
const addButton = document.getElementById("add-button");
const statusEl = document.getElementById("status");
const statsEl = document.getElementById("stats");
const browserEl = document.getElementById("browser");
const searchEl = document.getElementById("search");
const sortEl = document.getElementById("sort");
const tracksBody = document.getElementById("tracks-body");
const albumStripEl = document.getElementById("album-strip");
const albumModal = document.getElementById("album-modal");
const albumModalClose = document.getElementById("album-modal-close");
const albumModalCover = document.getElementById("album-modal-cover");
const albumModalTitle = document.getElementById("album-modal-title");
const albumModalMeta = document.getElementById("album-modal-meta");
const albumModalTracks = document.getElementById("album-modal-tracks");
const playlistPickerModal = document.getElementById("playlist-picker-modal");
const playlistPickerClose = document.getElementById("playlist-picker-close");
const playlistPickerTrack = document.getElementById("playlist-picker-track");
const playlistPickerSelect = document.getElementById("playlist-picker-select");
const playlistPickerAdd = document.getElementById("playlist-picker-add");
const playlistPickerCancel = document.getElementById("playlist-picker-cancel");
const openSettingsButton = document.getElementById("open-settings-button");
const settingsModal = document.getElementById("settings-modal");
const settingsClose = document.getElementById("settings-close");
const settingsCancel = document.getElementById("settings-cancel");
const settingsForm = document.getElementById("settings-form");
const settingsMusicDirectory = document.getElementById("settings-music-directory");
const settingsAutoSync = document.getElementById("settings-auto-sync");
const settingsDeleteAfterSync = document.getElementById("settings-delete-after-sync");
const settingsSave = document.getElementById("settings-save");

const playlistCreateForm = document.getElementById("playlist-create-form");
const playlistNameInput = document.getElementById("playlist-name-input");
const playlistCreateButton = document.getElementById("playlist-create-button");
const playlistListEl = document.getElementById("playlist-list");
const playlistEmptyEl = document.getElementById("playlist-empty");
const playlistDetailEl = document.getElementById("playlist-detail");
const playlistDetailNameEl = document.getElementById("playlist-detail-name");
const playlistDetailMetaEl = document.getElementById("playlist-detail-meta");
const playlistDeleteButton = document.getElementById("playlist-delete-button");
const playlistAddSelectedButton = document.getElementById("playlist-add-selected");
const playlistRemoveSelectedButton = document.getElementById("playlist-remove-selected");
const playlistTracksBody = document.getElementById("playlist-tracks-body");

let tracks = [];
let albums = [];
let playlists = [];
let selectedPlaylistName = "";
let currentMountpoint = "";
let actionInFlight = false;
let uploadInFlight = false;
const selectedTrackIds = new Set();
const selectedPlaylistTrackIds = new Set();
let playlistPickerTrackId = 0;
let playlistPickerTrackTitle = "";
let currentSettings = {
  music_directory: "",
  auto_sync_enabled: false,
  delete_after_sync: false,
};

const COVER_PLACEHOLDER = "/static/cover-placeholder.svg";
const ALLOWED_AUDIO_EXTENSIONS = new Set([".mp3", ".m4a", ".aac", ".wav", ".aiff", ".aif", ".flac", ".ogg", ".opus", ".m4b"]);

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("error", isError);
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const hrs = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return `${hrs}h ${mins}m`;
}

function formatTrackDuration(totalSeconds) {
  const seconds = Math.max(0, Math.floor(totalSeconds));
  const mins = Math.floor(seconds / 60);
  const sec = seconds % 60;
  return `${mins}:${String(sec).padStart(2, "0")}`;
}

function updateStats(data) {
  document.getElementById("track-count").textContent = data.track_count.toLocaleString();
  document.getElementById("artist-count").textContent = data.artist_count.toLocaleString();
  document.getElementById("album-count").textContent = data.album_count.toLocaleString();
  document.getElementById("duration-total").textContent = formatDuration(data.total_duration_seconds);
}

function normalizeAlbumKey(album) {
  return String(album || "Unknown Album")
    .trim()
    .toLowerCase();
}

function isEditablePlaylist(playlist) {
  return playlist && playlist.type === "playlist" && !playlist.smartpl;
}

function getSelectedPlaylist() {
  return playlists.find((playlist) => playlist.name === selectedPlaylistName) || null;
}

function getWritablePlaylists() {
  return playlists.filter((playlist) => isEditablePlaylist(playlist));
}

function coverUrl(track) {
  if (!track.artwork || !track.ipod_path || !currentMountpoint) {
    return COVER_PLACEHOLDER;
  }
  const mountpoint = encodeURIComponent(currentMountpoint);
  const ipodPath = encodeURIComponent(track.ipod_path);
  return `/api/cover?mountpoint=${mountpoint}&ipod_path=${ipodPath}`;
}

function updateWriteUi() {
  const busy = uploadInFlight || actionInFlight;
  musicFilesInput.disabled = busy;
  musicFolderInput.disabled = busy;
  musicSourceMode.disabled = busy;
  selectMusicButton.disabled = busy;
  clearSelectionButton.disabled = busy;
  addButton.disabled = busy;

  playlistNameInput.disabled = busy;
  playlistCreateButton.disabled = busy;

  const selectedPlaylist = getSelectedPlaylist();
  const editablePlaylist = selectedPlaylist && isEditablePlaylist(selectedPlaylist);
  playlistDeleteButton.disabled = busy || !editablePlaylist;
  playlistAddSelectedButton.disabled = busy || !editablePlaylist || selectedTrackIds.size === 0;
  playlistRemoveSelectedButton.disabled = busy || !editablePlaylist || selectedPlaylistTrackIds.size === 0;
  playlistPickerSelect.disabled = busy;
  playlistPickerAdd.disabled = busy;
  playlistPickerCancel.disabled = busy;
  playlistPickerClose.disabled = busy;
  openSettingsButton.disabled = busy;
  settingsClose.disabled = busy;
  settingsCancel.disabled = busy;
  settingsSave.disabled = busy;
  settingsMusicDirectory.disabled = busy;
  settingsAutoSync.disabled = busy;
  settingsDeleteAfterSync.disabled = busy;
}

function isSupportedAudioFile(file) {
  const name = String(file?.name || "").toLowerCase();
  const extIndex = name.lastIndexOf(".");
  if (extIndex === -1) {
    return false;
  }
  return ALLOWED_AUDIO_EXTENSIONS.has(name.slice(extIndex));
}

function collectSelectedFiles() {
  const combined = [...Array.from(musicFilesInput.files || []), ...Array.from(musicFolderInput.files || [])];
  const seen = new Set();
  const deduped = [];
  for (const file of combined) {
    if (!isSupportedAudioFile(file)) {
      continue;
    }
    const rel = file.webkitRelativePath || "";
    const key = `${rel}|${file.name}|${file.size}|${file.lastModified}`;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(file);
  }
  return deduped;
}

function updateSelectionSummary() {
  const rawCount = [...Array.from(musicFilesInput.files || []), ...Array.from(musicFolderInput.files || [])].length;
  const count = collectSelectedFiles().length;
  const ignored = Math.max(0, rawCount - count);
  if (!count) {
    selectionSummary.textContent = rawCount ? `No supported audio selected. Ignored ${ignored} file(s).` : "No files selected.";
    return;
  }
  selectionSummary.textContent = ignored
    ? `${count} audio file(s) selected. Ignored ${ignored} unsupported file(s).`
    : `${count} file(s) selected.`;
}

function clearSelectedFiles() {
  musicFilesInput.value = "";
  musicFolderInput.value = "";
  updateSelectionSummary();
}

function normalizePlaylistData(rawPlaylists) {
  return Array.from(rawPlaylists || [])
    .filter((item) => item && typeof item === "object")
    .map((item) => {
      const ids = Array.from(item.track_ids || [])
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value > 0);
      return {
        name: String(item.name || "Unknown"),
        type: String(item.type || "playlist"),
        count: Number(item.count || ids.length || 0),
        smartpl: Boolean(item.smartpl),
        track_ids: ids,
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

function pruneSelections() {
  const validTrackIds = new Set(
    tracks
      .map((track) => Number(track.id))
      .filter((id) => Number.isInteger(id) && id > 0),
  );

  for (const trackId of Array.from(selectedTrackIds)) {
    if (!validTrackIds.has(trackId)) {
      selectedTrackIds.delete(trackId);
    }
  }

  const selectedPlaylist = getSelectedPlaylist();
  const selectedPlaylistSet = new Set(selectedPlaylist?.track_ids || []);
  for (const trackId of Array.from(selectedPlaylistTrackIds)) {
    if (!selectedPlaylistSet.has(trackId)) {
      selectedPlaylistTrackIds.delete(trackId);
    }
  }
}

function buildAlbums() {
  const map = new Map();
  for (const track of tracks) {
    const albumName = String(track.album || "Unknown Album").trim() || "Unknown Album";
    const key = normalizeAlbumKey(albumName);
    if (!map.has(key)) {
      map.set(key, {
        key,
        album: albumName,
        representative: track,
        artists: new Set(),
        ipodPaths: new Set(),
        trackCount: 0,
      });
    }

    const item = map.get(key);
    item.trackCount += 1;
    item.artists.add(track.artist || "Unknown Artist");
    if (track.ipod_path) {
      item.ipodPaths.add(track.ipod_path);
    }
    if (track.artwork && !item.representative.artwork) {
      item.representative = track;
    }
  }

  albums = Array.from(map.values())
    .map((album) => ({
      key: album.key,
      album: album.album,
      representative: album.representative,
      artists: Array.from(album.artists),
      ipod_paths: Array.from(album.ipodPaths),
      track_count: album.trackCount,
    }))
    .sort((a, b) => a.album.localeCompare(b.album));
}

function renderAlbumStrip() {
  albumStripEl.innerHTML = albums
    .map((album) => {
      const src = coverUrl(album.representative);
      const label = escapeHtml(album.album || "Unknown Album");
      const artistsLabel = escapeHtml(album.artists.slice(0, 2).join(", "));
      return `
        <article class="album-card" data-album-key="${escapeHtml(album.key)}">
          <button class="album-delete" title="Delete album from iPod" data-album-key="${escapeHtml(album.key)}">x</button>
          <img loading="lazy" src="${src}" alt="${label}" onerror="this.src='${COVER_PLACEHOLDER}'" />
          <div class="album-meta">
            <p title="${label}">${label}</p>
            <p class="album-subtitle" title="${artistsLabel}">${artistsLabel} • ${album.track_count} track(s)</p>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderPlaylists() {
  if (!playlists.length) {
    playlistListEl.innerHTML = '<li class="playlist-empty-list">No playlists available.</li>';
    return;
  }

  playlistListEl.innerHTML = playlists
    .map((playlist) => {
      const activeClass = playlist.name === selectedPlaylistName ? "active" : "";
      const editable = isEditablePlaylist(playlist);
      const subtitle = editable
        ? `${playlist.count} track(s)`
        : `${playlist.type}${playlist.smartpl ? " • smart" : ""} • read-only`;
      const disabled = editable ? "" : "disabled";
      return `
        <li>
          <button type="button" class="playlist-item ${activeClass}" data-playlist-name="${escapeHtml(playlist.name)}" ${disabled}>
            <span>${escapeHtml(playlist.name)}</span>
            <span class="playlist-item-meta">${escapeHtml(subtitle)}</span>
          </button>
        </li>
      `;
    })
    .join("");
}

function renderPlaylistDetails() {
  const playlist = getSelectedPlaylist();
  if (!playlist) {
    playlistEmptyEl.classList.remove("hidden");
    playlistDetailEl.classList.add("hidden");
    playlistTracksBody.innerHTML = "";
    updateWriteUi();
    return;
  }

  playlistEmptyEl.classList.add("hidden");
  playlistDetailEl.classList.remove("hidden");

  const trackById = new Map();
  for (const track of tracks) {
    const id = Number(track.id);
    if (Number.isInteger(id) && id > 0) {
      trackById.set(id, track);
    }
  }

  const memberIds = Array.from(new Set((playlist.track_ids || []).filter((id) => Number.isInteger(id) && id > 0)));
  const memberIdSet = new Set(memberIds);
  for (const trackId of Array.from(selectedPlaylistTrackIds)) {
    if (!memberIdSet.has(trackId)) {
      selectedPlaylistTrackIds.delete(trackId);
    }
  }

  playlistDetailNameEl.textContent = playlist.name;
  playlistDetailMetaEl.textContent = `${playlist.count} track(s)`;

  if (!memberIds.length) {
    playlistTracksBody.innerHTML = '<tr><td colspan="5">Playlist is empty.</td></tr>';
    updateWriteUi();
    return;
  }

  playlistTracksBody.innerHTML = memberIds
    .map((trackId) => {
      const track = trackById.get(trackId);
      const checked = selectedPlaylistTrackIds.has(trackId) ? "checked" : "";
      if (!track) {
        return `
          <tr>
            <td><input type="checkbox" class="playlist-track-select" data-track-id="${trackId}" ${checked} /></td>
            <td>Unknown Track (#${trackId})</td>
            <td></td>
            <td></td>
            <td></td>
          </tr>
        `;
      }
      return `
        <tr>
          <td><input type="checkbox" class="playlist-track-select" data-track-id="${trackId}" ${checked} /></td>
          <td>${escapeHtml(track.title)}</td>
          <td>${escapeHtml(track.artist)}</td>
          <td>${escapeHtml(track.album)}</td>
          <td>${formatTrackDuration(track.duration_seconds)}</td>
        </tr>
      `;
    })
    .join("");

  updateWriteUi();
}

function applyFilters() {
  const query = searchEl.value.trim().toLowerCase();
  const sort = sortEl.value;
  let filtered = tracks.filter((track) => {
    if (!query) return true;
    const haystack = `${track.title} ${track.artist} ${track.album}`.toLowerCase();
    return haystack.includes(query);
  });

  filtered = filtered.sort((a, b) => {
    if (sort === "year") return b.year - a.year;
    if (sort === "duration") return b.duration_seconds - a.duration_seconds;
    return String(a[sort] || "").localeCompare(String(b[sort] || ""));
  });

  tracksBody.innerHTML = filtered
    .map((track) => {
      const numericTrackId = Number(track.id);
      const selectableTrackId = Number.isInteger(numericTrackId) && numericTrackId > 0 ? numericTrackId : 0;
      const checked = selectableTrackId > 0 && selectedTrackIds.has(selectableTrackId) ? "checked" : "";
      const selectCell = selectableTrackId
        ? `<input type="checkbox" class="track-select" data-track-id="${selectableTrackId}" ${checked} />`
        : "";

      return `
        <tr>
          <td>${selectCell}</td>
          <td class="cover-cell"><img class="cover-thumb" loading="lazy" src="${coverUrl(track)}" alt="" onerror="this.src='${COVER_PLACEHOLDER}'" /></td>
          <td>${escapeHtml(track.title)}</td>
          <td>${escapeHtml(track.artist)}</td>
          <td>${escapeHtml(track.album)}</td>
          <td>${track.year || ""}</td>
          <td>${formatTrackDuration(track.duration_seconds)}</td>
          <td>${track.bitrate ? `${track.bitrate} kbps` : ""}</td>
          <td class="actions-cell">
            <button class="action-btn action-playlist track-add-playlist" title="Add track to playlist" data-track-id="${selectableTrackId}" data-title="${escapeHtml(track.title)}">+</button>
            <button class="action-btn track-delete" title="Delete track from iPod" data-ipod-path="${escapeHtml(track.ipod_path)}" data-title="${escapeHtml(track.title)}">x</button>
          </td>
        </tr>
      `;
    })
    .join("");

  if (!filtered.length) {
    tracksBody.innerHTML = '<tr><td colspan="9">No tracks match the current filter.</td></tr>';
  }

  updateWriteUi();
}

function closeAlbumModal() {
  albumModal.classList.add("hidden");
  albumModalTracks.innerHTML = "";
}

function closePlaylistPicker() {
  playlistPickerModal.classList.add("hidden");
  playlistPickerTrackId = 0;
  playlistPickerTrackTitle = "";
  playlistPickerTrack.textContent = "";
  playlistPickerSelect.innerHTML = "";
}

function openPlaylistPicker(trackId, trackTitle) {
  const numericTrackId = Number(trackId);
  if (!Number.isInteger(numericTrackId) || numericTrackId <= 0) {
    setStatus("This track does not have a valid iPod ID.", true);
    return;
  }

  const writablePlaylists = getWritablePlaylists();
  if (!writablePlaylists.length) {
    setStatus("No writable playlists available. Create one first.", true);
    return;
  }

  playlistPickerTrackId = numericTrackId;
  playlistPickerTrackTitle = String(trackTitle || "Unknown Title");
  playlistPickerTrack.textContent = playlistPickerTrackTitle;
  playlistPickerSelect.innerHTML = writablePlaylists
    .map((playlist) => {
      const selected = playlist.name === selectedPlaylistName ? "selected" : "";
      return `<option value="${escapeHtml(playlist.name)}" ${selected}>${escapeHtml(playlist.name)}</option>`;
    })
    .join("");
  playlistPickerModal.classList.remove("hidden");
  updateWriteUi();
}

function applySettingsToForm(settings) {
  settingsMusicDirectory.value = String(settings.music_directory || "");
  settingsAutoSync.checked = Boolean(settings.auto_sync_enabled);
  settingsDeleteAfterSync.checked = Boolean(settings.delete_after_sync);
}

function normalizeSettingsPayload(payload) {
  return {
    music_directory: String(payload?.music_directory || ""),
    auto_sync_enabled: Boolean(payload?.auto_sync_enabled),
    delete_after_sync: Boolean(payload?.delete_after_sync),
  };
}

async function loadSettingsFromServer() {
  const response = await fetch("/api/settings");
  const data = await parseApiResponse(response, "Failed to load settings.");
  currentSettings = normalizeSettingsPayload(data);
  applySettingsToForm(currentSettings);
}

function openSettingsModal() {
  applySettingsToForm(currentSettings);
  settingsModal.classList.remove("hidden");
  updateWriteUi();
}

function closeSettingsModal() {
  settingsModal.classList.add("hidden");
}

function openAlbumModal(album) {
  const albumTracks = tracks
    .filter((track) => normalizeAlbumKey(track.album) === album.key)
    .sort((a, b) => String(a.title || "").localeCompare(String(b.title || "")));

  const totalDuration = albumTracks.reduce((sum, track) => sum + (track.duration_seconds || 0), 0);
  albumModalCover.src = coverUrl(album.representative);
  albumModalCover.onerror = () => {
    albumModalCover.src = COVER_PLACEHOLDER;
  };
  albumModalTitle.textContent = album.album;
  albumModalMeta.textContent = `${album.artists.join(", ")} • ${album.track_count} track(s) • ${formatDuration(totalDuration)}`;
  albumModalTracks.innerHTML = albumTracks
    .map(
      (track) => `
        <tr>
          <td>${escapeHtml(track.title)}</td>
          <td>${escapeHtml(track.artist)}</td>
          <td>${track.year || ""}</td>
          <td>${formatTrackDuration(track.duration_seconds)}</td>
          <td>${track.bitrate ? `${track.bitrate} kbps` : ""}</td>
          <td>
            <button class="action-btn action-playlist album-track-add-playlist" title="Add track to playlist" data-track-id="${Number(track.id) || 0}" data-title="${escapeHtml(track.title)}">+</button>
          </td>
        </tr>
      `,
    )
    .join("");

  albumModal.classList.remove("hidden");
}

async function parseApiResponse(response, fallbackMessage) {
  const contentType = String(response.headers.get("content-type") || "").toLowerCase();
  if (contentType.includes("application/json")) {
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || fallbackMessage);
    }
    return data;
  }

  const text = (await response.text()).trim();
  if (!response.ok) {
    throw new Error(text || fallbackMessage);
  }
  throw new Error(text || fallbackMessage);
}

async function loadLibrary(mountpoint, showLoadingStatus = true) {
  if (showLoadingStatus) {
    setStatus(`Loading library from ${mountpoint} ...`);
  }
  loadButton.disabled = true;
  try {
    const response = await fetch(`/api/library?mountpoint=${encodeURIComponent(mountpoint)}`);
    const data = await parseApiResponse(response, "Failed to load iPod library.");

    currentMountpoint = data.mountpoint;
    tracks = data.tracks || [];
    playlists = normalizePlaylistData(data.playlists || []);
    closeAlbumModal();
    buildAlbums();

    if (!playlists.some((playlist) => playlist.name === selectedPlaylistName && isEditablePlaylist(playlist))) {
      const firstEditable = playlists.find((playlist) => isEditablePlaylist(playlist));
      selectedPlaylistName = firstEditable ? firstEditable.name : "";
      selectedPlaylistTrackIds.clear();
    }

    pruneSelections();
    updateStats(data);
    renderAlbumStrip();
    renderPlaylists();
    renderPlaylistDetails();
    applyFilters();
    updateWriteUi();

    statsEl.classList.remove("hidden");
    browserEl.classList.remove("hidden");
    if (showLoadingStatus) {
      const loadedMessage = `Loaded ${data.track_count.toLocaleString()} tracks from ${data.mountpoint}.`;
      const syncMessage = String(data?.auto_sync?.message || "").trim();
      setStatus(syncMessage ? `${syncMessage} ${loadedMessage}` : loadedMessage);
    }
  } catch (error) {
    currentMountpoint = "";
    tracks = [];
    albums = [];
    playlists = [];
    selectedPlaylistName = "";
    selectedTrackIds.clear();
    selectedPlaylistTrackIds.clear();
    closeAlbumModal();
    albumStripEl.innerHTML = "";
    playlistListEl.innerHTML = "";
    playlistTracksBody.innerHTML = "";
    statsEl.classList.add("hidden");
    browserEl.classList.add("hidden");
    updateWriteUi();
    setStatus(error.message, true);
  } finally {
    loadButton.disabled = false;
  }
}

async function deleteByPaths(ipodPaths, descriptor) {
  if (actionInFlight || uploadInFlight) {
    return;
  }
  if (!currentMountpoint) {
    setStatus("Load a library first.", true);
    return;
  }

  actionInFlight = true;
  updateWriteUi();
  setStatus(`Deleting ${descriptor} ...`);
  try {
    const response = await fetch("/api/delete-tracks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mountpoint: currentMountpoint,
        ipod_paths: ipodPaths,
      }),
    });
    const data = await parseApiResponse(response, "Failed to delete from iPod.");

    await loadLibrary(currentMountpoint, false);
    setStatus(data.message);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    actionInFlight = false;
    updateWriteUi();
  }
}

async function runPlaylistMutation(endpoint, payload, actionStatus) {
  if (actionInFlight || uploadInFlight) {
    return;
  }
  if (!currentMountpoint) {
    setStatus("Load your iPod library first.", true);
    return;
  }

  const keepSelectedName = selectedPlaylistName;
  let success = false;
  actionInFlight = true;
  updateWriteUi();
  setStatus(actionStatus);
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await parseApiResponse(response, "Playlist operation failed.");

    await loadLibrary(currentMountpoint, false);
    if (playlists.some((playlist) => playlist.name === keepSelectedName && isEditablePlaylist(playlist))) {
      selectedPlaylistName = keepSelectedName;
      renderPlaylists();
      renderPlaylistDetails();
    }
    setStatus(data.message || "Playlist operation completed.");
    success = true;
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    actionInFlight = false;
    updateWriteUi();
  }
  return success;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const mountpoint = mountpointInput.value.trim();
  if (!mountpoint) {
    setStatus("Mountpoint is required.", true);
    return;
  }
  await loadLibrary(mountpoint);
});

addForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (uploadInFlight || actionInFlight) {
    return;
  }
  if (!currentMountpoint) {
    setStatus("Load your iPod library first before adding files.", true);
    return;
  }

  const files = collectSelectedFiles();
  if (!files.length) {
    setStatus("Select one or more files or a folder to add.", true);
    return;
  }

  const formData = new FormData();
  formData.append("mountpoint", currentMountpoint);
  for (const file of files) {
    formData.append("files", file);
  }

  uploadInFlight = true;
  updateWriteUi();
  setStatus(`Adding ${files.length} file(s) to iPod ...`);
  try {
    const response = await fetch("/api/add-tracks", {
      method: "POST",
      body: formData,
    });
    const data = await parseApiResponse(response, "Failed to add tracks.");

    clearSelectedFiles();
    await loadLibrary(currentMountpoint, false);
    setStatus(data.message || `Added ${files.length} track(s).`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    uploadInFlight = false;
    updateWriteUi();
  }
});

playlistCreateForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const playlistName = playlistNameInput.value.trim();
  if (!playlistName) {
    setStatus("Playlist name is required.", true);
    return;
  }

  const success = await runPlaylistMutation(
    "/api/playlists/create",
    {
      mountpoint: currentMountpoint,
      playlist_name: playlistName,
    },
    `Creating playlist "${playlistName}" ...`,
  );
  if (!success) {
    return;
  }
  selectedPlaylistName = playlistName;
  selectedPlaylistTrackIds.clear();
  renderPlaylists();
  renderPlaylistDetails();
  playlistNameInput.value = "";
});

playlistDeleteButton.addEventListener("click", async () => {
  const playlist = getSelectedPlaylist();
  if (!playlist || !isEditablePlaylist(playlist)) {
    return;
  }

  const success = await runPlaylistMutation(
    "/api/playlists/delete",
    {
      mountpoint: currentMountpoint,
      playlist_name: playlist.name,
    },
    `Deleting playlist "${playlist.name}" ...`,
  );
  if (!success) {
    return;
  }
  selectedPlaylistTrackIds.clear();
});

playlistAddSelectedButton.addEventListener("click", async () => {
  const playlist = getSelectedPlaylist();
  if (!playlist || !isEditablePlaylist(playlist)) {
    setStatus("Select a writable playlist first.", true);
    return;
  }
  if (!selectedTrackIds.size) {
    setStatus("Select one or more library tracks first.", true);
    return;
  }

  await runPlaylistMutation(
    "/api/playlists/add-tracks",
    {
      mountpoint: currentMountpoint,
      playlist_name: playlist.name,
      track_ids: Array.from(selectedTrackIds),
    },
    `Adding ${selectedTrackIds.size} selected track(s) to "${playlist.name}" ...`,
  );
});

playlistRemoveSelectedButton.addEventListener("click", async () => {
  const playlist = getSelectedPlaylist();
  if (!playlist || !isEditablePlaylist(playlist)) {
    setStatus("Select a writable playlist first.", true);
    return;
  }
  if (!selectedPlaylistTrackIds.size) {
    setStatus("Select one or more playlist tracks first.", true);
    return;
  }

  const success = await runPlaylistMutation(
    "/api/playlists/remove-tracks",
    {
      mountpoint: currentMountpoint,
      playlist_name: playlist.name,
      track_ids: Array.from(selectedPlaylistTrackIds),
    },
    `Removing ${selectedPlaylistTrackIds.size} selected track(s) from "${playlist.name}" ...`,
  );
  if (!success) {
    return;
  }
  selectedPlaylistTrackIds.clear();
});

playlistListEl.addEventListener("click", (event) => {
  const button = event.target.closest(".playlist-item");
  if (!button || button.disabled) {
    return;
  }
  const playlistName = String(button.dataset.playlistName || "").trim();
  if (!playlistName) {
    return;
  }
  selectedPlaylistName = playlistName;
  selectedPlaylistTrackIds.clear();
  renderPlaylists();
  renderPlaylistDetails();
});

playlistTracksBody.addEventListener("change", (event) => {
  const checkbox = event.target.closest(".playlist-track-select");
  if (!checkbox) {
    return;
  }
  const trackId = Number(checkbox.dataset.trackId || 0);
  if (!Number.isInteger(trackId) || trackId <= 0) {
    return;
  }
  if (checkbox.checked) {
    selectedPlaylistTrackIds.add(trackId);
  } else {
    selectedPlaylistTrackIds.delete(trackId);
  }
  updateWriteUi();
});

searchEl.addEventListener("input", applyFilters);
sortEl.addEventListener("change", applyFilters);

tracksBody.addEventListener("change", (event) => {
  const checkbox = event.target.closest(".track-select");
  if (!checkbox) {
    return;
  }

  const trackId = Number(checkbox.dataset.trackId || 0);
  if (!Number.isInteger(trackId) || trackId <= 0) {
    return;
  }
  if (checkbox.checked) {
    selectedTrackIds.add(trackId);
  } else {
    selectedTrackIds.delete(trackId);
  }
  updateWriteUi();
});

tracksBody.addEventListener("click", async (event) => {
  const addButton = event.target.closest(".track-add-playlist");
  if (addButton) {
    const trackId = Number(addButton.dataset.trackId || 0);
    const title = addButton.dataset.title || "Unknown Title";
    openPlaylistPicker(trackId, title);
    return;
  }

  const button = event.target.closest(".track-delete");
  if (!button) {
    return;
  }

  const ipodPath = button.dataset.ipodPath;
  const title = button.dataset.title || "this track";
  if (!ipodPath) {
    return;
  }

  await deleteByPaths([ipodPath], `track "${title}"`);
});

albumModalTracks.addEventListener("click", (event) => {
  const button = event.target.closest(".album-track-add-playlist");
  if (!button) {
    return;
  }
  const trackId = Number(button.dataset.trackId || 0);
  const title = button.dataset.title || "Unknown Title";
  openPlaylistPicker(trackId, title);
});

albumStripEl.addEventListener("click", async (event) => {
  const deleteButton = event.target.closest(".album-delete");
  if (deleteButton) {
    const key = deleteButton.dataset.albumKey;
    const album = albums.find((item) => item.key === key);
    if (!album) {
      return;
    }
    await deleteByPaths(album.ipod_paths, `album "${album.album}"`);
    return;
  }

  const card = event.target.closest(".album-card");
  if (!card) {
    return;
  }
  const key = card.dataset.albumKey;
  const album = albums.find((item) => item.key === key);
  if (!album) {
    return;
  }
  openAlbumModal(album);
});

albumModalClose.addEventListener("click", () => {
  closeAlbumModal();
});

albumModal.addEventListener("click", (event) => {
  if (event.target === albumModal) {
    closeAlbumModal();
  }
});

playlistPickerClose.addEventListener("click", () => {
  closePlaylistPicker();
});

playlistPickerCancel.addEventListener("click", () => {
  closePlaylistPicker();
});

playlistPickerModal.addEventListener("click", (event) => {
  if (event.target === playlistPickerModal) {
    closePlaylistPicker();
  }
});

playlistPickerAdd.addEventListener("click", async () => {
  const playlistName = String(playlistPickerSelect.value || "").trim();
  if (!playlistName) {
    setStatus("Select a playlist.", true);
    return;
  }
  if (!playlistPickerTrackId) {
    setStatus("No track selected.", true);
    return;
  }

  const success = await runPlaylistMutation(
    "/api/playlists/add-tracks",
    {
      mountpoint: currentMountpoint,
      playlist_name: playlistName,
      track_ids: [playlistPickerTrackId],
    },
    `Adding "${playlistPickerTrackTitle}" to "${playlistName}" ...`,
  );
  if (!success) {
    return;
  }
  closePlaylistPicker();
});

openSettingsButton.addEventListener("click", async () => {
  try {
    await loadSettingsFromServer();
    openSettingsModal();
  } catch (error) {
    setStatus(error.message, true);
  }
});

settingsClose.addEventListener("click", () => {
  closeSettingsModal();
});

settingsCancel.addEventListener("click", () => {
  closeSettingsModal();
});

settingsModal.addEventListener("click", (event) => {
  if (event.target === settingsModal) {
    closeSettingsModal();
  }
});

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (uploadInFlight || actionInFlight) {
    return;
  }

  const payload = {
    music_directory: settingsMusicDirectory.value.trim(),
    auto_sync_enabled: settingsAutoSync.checked,
    delete_after_sync: settingsDeleteAfterSync.checked,
  };

  actionInFlight = true;
  updateWriteUi();
  setStatus("Saving settings ...");
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await parseApiResponse(response, "Failed to save settings.");
    currentSettings = normalizeSettingsPayload(data);
    applySettingsToForm(currentSettings);
    closeSettingsModal();
    setStatus("Settings saved.");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    actionInFlight = false;
    updateWriteUi();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !settingsModal.classList.contains("hidden")) {
    closeSettingsModal();
    return;
  }
  if (event.key === "Escape" && !playlistPickerModal.classList.contains("hidden")) {
    closePlaylistPicker();
    return;
  }
  if (event.key === "Escape" && !albumModal.classList.contains("hidden")) {
    closeAlbumModal();
  }
});

selectMusicButton.addEventListener("click", () => {
  if (uploadInFlight) {
    return;
  }
  if (musicSourceMode.value === "folder") {
    musicFolderInput.click();
  } else {
    musicFilesInput.click();
  }
});

clearSelectionButton.addEventListener("click", () => {
  if (uploadInFlight) {
    return;
  }
  clearSelectedFiles();
});

musicFilesInput.addEventListener("change", updateSelectionSummary);
musicFolderInput.addEventListener("change", updateSelectionSummary);
musicSourceMode.addEventListener("change", () => {
  clearSelectedFiles();
});
updateSelectionSummary();
loadSettingsFromServer().catch(() => {});
updateWriteUi();
