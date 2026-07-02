#include <ctype.h>
#include <getopt.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <glib.h>
#include <gpod/itdb.h>

typedef enum {
    ACTION_NONE = 0,
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_ADD,
    ACTION_REMOVE
} PlaylistAction;

typedef struct {
    const char* mountpoint;
    const char* playlist_name;
    PlaylistAction action;
    GArray* track_ids;
} Options;

static void usage(const char* argv0) {
    fprintf(
        stderr,
        "usage: %s -M <mountpoint> --action <create|delete|add|remove> --playlist <name> [--track-id <id> ...]\n",
        argv0
    );
}

static PlaylistAction parse_action(const char* action) {
    if (!action) {
        return ACTION_NONE;
    }
    if (strcmp(action, "create") == 0) {
        return ACTION_CREATE;
    }
    if (strcmp(action, "delete") == 0) {
        return ACTION_DELETE;
    }
    if (strcmp(action, "add") == 0) {
        return ACTION_ADD;
    }
    if (strcmp(action, "remove") == 0) {
        return ACTION_REMOVE;
    }
    return ACTION_NONE;
}

static bool playlist_has_track(const Itdb_Playlist* playlist, const Itdb_Track* track) {
    for (GList* it = playlist->members; it != NULL; it = it->next) {
        const Itdb_Track* member = (const Itdb_Track*)it->data;
        if (member == track || member->id == track->id) {
            return true;
        }
    }
    return false;
}

static bool playlist_is_readonly(const Itdb_Playlist* playlist) {
    if (itdb_playlist_is_mpl((Itdb_Playlist*)playlist) || playlist->is_spl) {
        return true;
    }
    if (playlist->name && g_ascii_strcasecmp(playlist->name, "Podcasts") == 0) {
        return true;
    }
    return false;
}

int main(int argc, char** argv) {
    Options opts = {
        .mountpoint = NULL,
        .playlist_name = NULL,
        .action = ACTION_NONE,
        .track_ids = g_array_new(FALSE, FALSE, sizeof(guint32)),
    };

    const struct option long_options[] = {
        {"mount-point", required_argument, NULL, 'M'},
        {"action", required_argument, NULL, 'a'},
        {"playlist", required_argument, NULL, 'p'},
        {"track-id", required_argument, NULL, 't'},
        {"help", no_argument, NULL, 'h'},
        {0, 0, 0, 0},
    };

    int option_index = 0;
    int c = 0;
    while ((c = getopt_long(argc, argv, "M:a:p:t:h", long_options, &option_index)) != -1) {
        switch (c) {
            case 'M':
                opts.mountpoint = optarg;
                break;
            case 'a':
                opts.action = parse_action(optarg);
                break;
            case 'p':
                opts.playlist_name = optarg;
                break;
            case 't': {
                char* endptr = NULL;
                unsigned long parsed = strtoul(optarg, &endptr, 10);
                if (endptr == optarg || *endptr != '\0' || parsed == 0 || parsed > UINT32_MAX) {
                    fprintf(stderr, "invalid track id: %s\n", optarg);
                    g_array_free(opts.track_ids, TRUE);
                    return 2;
                }
                guint32 id = (guint32)parsed;
                g_array_append_val(opts.track_ids, id);
                break;
            }
            case 'h':
                usage(argv[0]);
                g_array_free(opts.track_ids, TRUE);
                return 0;
            default:
                usage(argv[0]);
                g_array_free(opts.track_ids, TRUE);
                return 2;
        }
    }

    if (!opts.mountpoint || !opts.playlist_name || opts.action == ACTION_NONE) {
        usage(argv[0]);
        g_array_free(opts.track_ids, TRUE);
        return 2;
    }

    GError* error = NULL;
    Itdb_iTunesDB* itdb = itdb_parse(opts.mountpoint, &error);
    if (error || !itdb) {
        fprintf(
            stderr,
            "failed to parse iTunesDB at %s - %s\n",
            opts.mountpoint,
            (error && error->message) ? error->message : "unknown error"
        );
        if (error) {
            g_error_free(error);
        }
        g_array_free(opts.track_ids, TRUE);
        return 1;
    }

    Itdb_Playlist* playlist = itdb_playlist_by_name(itdb, (gchar*)opts.playlist_name);
    bool changed = false;

    if (opts.action == ACTION_CREATE) {
        if (!playlist) {
            playlist = itdb_playlist_new(opts.playlist_name, FALSE);
            itdb_playlist_add(itdb, playlist, -1);
            changed = true;
        } else if (playlist_is_readonly(playlist)) {
            fprintf(stderr, "playlist `%s` is read-only\n", opts.playlist_name);
            itdb_free(itdb);
            g_array_free(opts.track_ids, TRUE);
            return 1;
        }
    } else if (opts.action == ACTION_DELETE) {
        if (!playlist) {
            fprintf(stdout, "playlist `%s` not found, nothing to delete\n", opts.playlist_name);
        } else if (playlist_is_readonly(playlist)) {
            fprintf(stderr, "playlist `%s` is read-only\n", opts.playlist_name);
            itdb_free(itdb);
            g_array_free(opts.track_ids, TRUE);
            return 1;
        } else {
            itdb_playlist_remove(playlist);
            changed = true;
        }
    } else {
        if (!playlist) {
            fprintf(stderr, "playlist `%s` not found\n", opts.playlist_name);
            itdb_free(itdb);
            g_array_free(opts.track_ids, TRUE);
            return 1;
        }
        if (playlist_is_readonly(playlist)) {
            fprintf(stderr, "playlist `%s` is read-only\n", opts.playlist_name);
            itdb_free(itdb);
            g_array_free(opts.track_ids, TRUE);
            return 1;
        }
        if (opts.track_ids->len == 0) {
            fprintf(stderr, "no track ids provided\n");
            itdb_free(itdb);
            g_array_free(opts.track_ids, TRUE);
            return 1;
        }

        GTree* id_tree = itdb_track_id_tree_create(itdb);
        guint added = 0;
        guint removed = 0;
        guint missing = 0;

        for (guint i = 0; i < opts.track_ids->len; i++) {
            const guint32 track_id = g_array_index(opts.track_ids, guint32, i);
            Itdb_Track* track = itdb_track_id_tree_by_id(id_tree, track_id);
            if (!track) {
                missing++;
                continue;
            }

            const bool exists = playlist_has_track(playlist, track);
            if (opts.action == ACTION_ADD) {
                if (!exists) {
                    itdb_playlist_add_track(playlist, track, -1);
                    added++;
                    changed = true;
                }
            } else if (opts.action == ACTION_REMOVE) {
                if (exists) {
                    itdb_playlist_remove_track(playlist, track);
                    removed++;
                    changed = true;
                }
            }
        }

        if (opts.action == ACTION_ADD) {
            fprintf(stdout, "playlist `%s`: added=%u missing=%u\n", opts.playlist_name, added, missing);
        } else {
            fprintf(stdout, "playlist `%s`: removed=%u missing=%u\n", opts.playlist_name, removed, missing);
        }

        itdb_track_id_tree_destroy(id_tree);
    }

    if (changed) {
        itdb_write(itdb, &error);
        if (error) {
            fprintf(
                stderr,
                "failed to write iTunesDB - %s\n",
                error->message ? error->message : "unknown error"
            );
            g_error_free(error);
            itdb_free(itdb);
            g_array_free(opts.track_ids, TRUE);
            return 1;
        }
    }

    itdb_free(itdb);
    g_array_free(opts.track_ids, TRUE);
    return 0;
}
