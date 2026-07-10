from __future__ import annotations

from tools.verification import (
    EVIDENCE_CALL,
    EVIDENCE_LIVE_FETCH,
    EVIDENCE_PRIOR_TOOL,
    EVIDENCE_USER_GOAL,
    FETCH_YANDEX_TRACK,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARN,
    EvidenceRef,
    VerificationQuestion,
)

_USER_GOAL = EvidenceRef(kind=EVIDENCE_USER_GOAL, optional=True, label="user_goal")

_LIVE_YANDEX_TRACK = EvidenceRef(
    kind=EVIDENCE_LIVE_FETCH,
    fetch=FETCH_YANDEX_TRACK,
    label="yandex_track_live",
)

_PRIOR_YM_SEARCH = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("yandex.music.search", "yandex.music.search_suggest"),
    optional=True,
    max_age_steps=10,
    label="prior_ym_search",
)

_PRIOR_YM_TRACK = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "yandex.music.search",
        "yandex.music.tracks",
        "yandex.music.tracks_full_info",
        "yandex.music.users_likes_tracks",
        "yandex.music.rotor_station_tracks",
    ),
    match=(("track_id", "$call.track_id"), ("track_ids", "$call.track_ids")),
    optional=True,
    max_age_steps=10,
    label="prior_ym_track",
)

_PRIOR_YM_ALBUM = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("yandex.music.search", "yandex.music.albums", "yandex.music.albums_with_tracks"),
    match=(("album_id", "$call.album_id"), ("album_ids", "$call.album_ids")),
    optional=True,
    max_age_steps=10,
    label="prior_ym_album",
)

_PRIOR_YM_ARTIST = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=("yandex.music.search", "yandex.music.artists", "yandex.music.artists_tracks"),
    match=(("artist_id", "$call.artist_id"), ("artist_ids", "$call.artist_ids")),
    optional=True,
    max_age_steps=10,
    label="prior_ym_artist",
)

_PRIOR_YM_PLAYLIST = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_names=(
        "yandex.music.search",
        "yandex.music.playlist",
        "yandex.music.playlists",
        "yandex.music.users_playlists_list",
    ),
    match=(("playlist_uuid", "$call.playlist_uuid"), ("playlist_ids", "$call.playlist_ids"), ("kind", "$call.kind")),
    optional=True,
    max_age_steps=10,
    label="prior_ym_playlist",
)

_PRIOR_YM_CONTEXT = EvidenceRef(
    kind=EVIDENCE_PRIOR_TOOL,
    tool_name_pattern="yandex.music.*",
    optional=True,
    max_age_steps=10,
    label="prior_ym_context",
)


def _call(label: str, *fields: str) -> EvidenceRef:
    return EvidenceRef(kind=EVIDENCE_CALL, fields=fields, label=label)


# --- Tier 1: discovery & read ---

YANDEX_MUSIC_SEARCH_QUESTIONS = (
    VerificationQuestion(
        id="query_matches_intent",
        text="Does text match what the user asked to find on Yandex Music (not Exa/Drive/Maps)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("search_call", "text", "type_", "page"), _USER_GOAL),
    ),
    VerificationQuestion(
        id="type_scope",
        text="Does type_ filter (track/album/artist/playlist) match the entity the user wants?",
        severity=SEVERITY_WARN,
        evidence=(_call("search_call", "type_"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_SEARCH_SUGGEST_QUESTIONS = (
    VerificationQuestion(
        id="partial_query_matches",
        text="Does part match the partial query the user is typing for autocomplete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("suggest_call", "part"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_TRACKS_QUESTIONS = (
    VerificationQuestion(
        id="track_ids_correct",
        text="Do track_ids match tracks from search or the user's link (trackId or trackId:albumId)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("tracks_call", "track_ids"), _USER_GOAL, _PRIOR_YM_SEARCH, _PRIOR_YM_CONTEXT),
    ),
)

YANDEX_MUSIC_ALBUMS_QUESTIONS = (
    VerificationQuestion(
        id="album_ids_correct",
        text="Do album_ids match albums the user asked about from search or URL?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("albums_call", "album_ids"), _USER_GOAL, _PRIOR_YM_SEARCH),
    ),
)

YANDEX_MUSIC_ALBUMS_WITH_TRACKS_QUESTIONS = (
    VerificationQuestion(
        id="album_id_correct",
        text="Is album_id the album whose track listing the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("albums_tracks_call", "album_id"), _USER_GOAL, _PRIOR_YM_ALBUM, _PRIOR_YM_SEARCH),
    ),
)

YANDEX_MUSIC_ARTISTS_QUESTIONS = (
    VerificationQuestion(
        id="artist_ids_correct",
        text="Do artist_ids match the artist(s) the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("artists_call", "artist_ids"), _USER_GOAL, _PRIOR_YM_SEARCH),
    ),
)

YANDEX_MUSIC_ARTISTS_TRACKS_QUESTIONS = (
    VerificationQuestion(
        id="artist_id_correct",
        text="Is artist_id the artist whose tracks the user asked to list?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("artists_tracks_call", "artist_id", "page", "page_size"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
)

YANDEX_MUSIC_TRACKS_LYRICS_QUESTIONS = (
    VerificationQuestion(
        id="track_id_correct",
        text="Is track_id the song whose lyrics the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("lyrics_call", "track_id"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_TRACKS_FULL_INFO_QUESTIONS = (
    VerificationQuestion(
        id="track_id_correct",
        text="Is track_id the track the user asked detailed info about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("full_info_call", "track_id"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_PLAYLIST_QUESTIONS = (
    VerificationQuestion(
        id="playlist_uuid_correct",
        text="Is playlist_uuid the playlist the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("playlist_call", "playlist_uuid"), _USER_GOAL, _PRIOR_YM_SEARCH, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_PLAYLISTS_QUESTIONS = (
    VerificationQuestion(
        id="playlist_ids_correct",
        text="Do playlist_ids match playlists the user asked to fetch?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("playlists_call", "playlist_ids"), _USER_GOAL, _PRIOR_YM_SEARCH),
    ),
)

YANDEX_MUSIC_USERS_PLAYLISTS_LIST_QUESTIONS = (
    VerificationQuestion(
        id="user_library_intent",
        text="Did the user ask for their own playlists (not catalog playlist or metatag)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_YM_CONTEXT),
    ),
)

YANDEX_MUSIC_USERS_LIKES_TRACKS_QUESTIONS = (
    VerificationQuestion(
        id="likes_library_intent",
        text="Did the user ask for their «Мне нравится» tracks (auth required)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_LIKES_ALBUMS_QUESTIONS = (
    VerificationQuestion(
        id="likes_albums_intent",
        text="Did the user ask for liked albums in their library?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_LIKES_ARTISTS_QUESTIONS = (
    VerificationQuestion(
        id="likes_artists_intent",
        text="Did the user ask for liked artists in their library?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_FEED_QUESTIONS = (
    VerificationQuestion(
        id="feed_recommendations_intent",
        text="Did the user ask for home feed/recommendations, not a specific search?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_PLAYLISTS_PERSONAL_QUESTIONS = (
    VerificationQuestion(
        id="personal_mix_intent",
        text="Does playlist_id match the personal mix the user asked for?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("personal_call", "playlist_id"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_ROTOR_STATION_TRACKS_QUESTIONS = (
    VerificationQuestion(
        id="station_matches_intent",
        text="Is station the radio/wave the user asked to play tracks from?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("rotor_tracks_call", "station", "queue"), _USER_GOAL, _PRIOR_YM_CONTEXT),
    ),
    VerificationQuestion(
        id="radio_not_search",
        text="Did the user want personalized radio, not catalog search?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_ROTOR_STATIONS_DASHBOARD_QUESTIONS = (
    VerificationQuestion(
        id="dashboard_intent",
        text="Did the user ask to browse recommended radio stations?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_MUSIC_HISTORY_QUESTIONS = (
    VerificationQuestion(
        id="history_intent",
        text="Did the user ask for listening history (auth required)?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_QUEUE_QUESTIONS = (
    VerificationQuestion(
        id="queue_id_correct",
        text="Is queue_id the playback queue the user asked about?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("queue_call", "queue_id"), _USER_GOAL, _PRIOR_YM_CONTEXT),
    ),
)

YANDEX_MUSIC_QUEUES_LIST_QUESTIONS = (
    VerificationQuestion(
        id="queues_list_intent",
        text="Did the user ask to list playback queues across devices?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_TRACK_DOWNLOAD_QUESTIONS = (
    VerificationQuestion(
        id="track_id_correct",
        text="Is track_id from search/user link (trackId or trackId:albumId), not guessed?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("download_call", "track_id", "codec"), _USER_GOAL, _PRIOR_YM_TRACK, _PRIOR_YM_SEARCH),
    ),
    VerificationQuestion(
        id="not_download_info",
        text="Did the user want a downloadable file (track_download), not tracks_download_info metadata only?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL, _PRIOR_YM_CONTEXT),
    ),
    VerificationQuestion(
        id="send_chain_intent",
        text="If sending in Telegram, is track_download followed by telegram.send_file with returned file_ref?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="track_exists_live",
        text="Does live yandex.music.tracks confirm the track exists after download?",
        severity=SEVERITY_WARN,
        evidence=(_call("download_call", "track_id"), _LIVE_YANDEX_TRACK, _USER_GOAL),
    ),
)

# --- Tier 2: writes ---

YANDEX_MUSIC_ACCOUNT_SETTINGS_SET_QUESTIONS = (
    VerificationQuestion(
        id="setting_matches_intent",
        text="Do param/value change the account setting the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("settings_set_call", "param", "value", "data"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_CONSUME_PROMO_CODE_QUESTIONS = (
    VerificationQuestion(
        id="code_matches",
        text="Is code the promo the user asked to activate?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("promo_call", "code"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_PIN_ALBUM_QUESTIONS = (
    VerificationQuestion(
        id="album_id_correct",
        text="Is album_id the album the user asked to pin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("pin_album_call", "album_id"), _USER_GOAL, _PRIOR_YM_ALBUM),
    ),
)

YANDEX_MUSIC_PIN_ARTIST_QUESTIONS = (
    VerificationQuestion(
        id="artist_id_correct",
        text="Is artist_id the artist the user asked to pin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("pin_artist_call", "artist_id"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
)

YANDEX_MUSIC_PIN_PLAYLIST_QUESTIONS = (
    VerificationQuestion(
        id="playlist_target",
        text="Are uid and kind the playlist the user asked to pin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("pin_playlist_call", "uid", "kind"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_PIN_WAVE_QUESTIONS = (
    VerificationQuestion(
        id="seeds_correct",
        text="Are seeds the wave the user asked to pin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("pin_wave_call", "seeds"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_UNPIN_ALBUM_QUESTIONS = (
    VerificationQuestion(
        id="album_id_correct",
        text="Is album_id the pinned album the user asked to unpin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unpin_album_call", "album_id"), _USER_GOAL, _PRIOR_YM_ALBUM),
    ),
)

YANDEX_MUSIC_UNPIN_ARTIST_QUESTIONS = (
    VerificationQuestion(
        id="artist_id_correct",
        text="Is artist_id the pinned artist the user asked to unpin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unpin_artist_call", "artist_id"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
)

YANDEX_MUSIC_UNPIN_PLAYLIST_QUESTIONS = (
    VerificationQuestion(
        id="playlist_target",
        text="Are uid and kind the playlist the user asked to unpin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unpin_playlist_call", "uid", "kind"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_UNPIN_WAVE_QUESTIONS = (
    VerificationQuestion(
        id="seeds_correct",
        text="Are seeds the wave the user asked to unpin?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("unpin_wave_call", "seeds"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_PLAY_AUDIO_QUESTIONS = (
    VerificationQuestion(
        id="track_target",
        text="Are track_id and album_id the track the user asked to mark as playing?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("play_audio_call", "track_id", "album_id", "from"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
    VerificationQuestion(
        id="play_not_download",
        text="Did the user want playback telemetry, not download/send file?",
        severity=SEVERITY_INFO,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_PLAYLISTS_COLLECTIVE_JOIN_QUESTIONS = (
    VerificationQuestion(
        id="join_token_target",
        text="Are user_id and token the collaborative playlist invite the user asked to join?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("collective_join_call", "user_id", "token"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_QUEUE_CREATE_QUESTIONS = (
    VerificationQuestion(
        id="queue_payload_matches",
        text="Does queue payload match tracks/order the user asked to queue?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("queue_create_call", "queue", "device"), _USER_GOAL, _PRIOR_YM_CONTEXT),
    ),
)

YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_QUESTIONS = (
    VerificationQuestion(
        id="feedback_explicit_intent",
        text="Did the user explicitly ask to train/skip/rate radio (not passive listening)?",
        severity=SEVERITY_CRITICAL,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="station_and_type",
        text="Are station and type_ the correct radio feedback event?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("feedback_call", "station", "type_", "track_id"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_RADIO_STARTED_QUESTIONS = (
    VerificationQuestion(
        id="feedback_explicit_intent",
        text="Did the user explicitly want radio-started feedback sent?",
        severity=SEVERITY_CRITICAL,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="station_correct",
        text="Is station the radio station that was started?",
        severity=SEVERITY_WARN,
        evidence=(_call("radio_started_call", "station"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_SKIP_QUESTIONS = (
    VerificationQuestion(
        id="skip_explicit_intent",
        text="Did the user explicitly skip/dislike this radio track?",
        severity=SEVERITY_CRITICAL,
        evidence=(_USER_GOAL,),
    ),
    VerificationQuestion(
        id="skip_target",
        text="Are station, track_id, and total_played_seconds correct for the skip event?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("skip_call", "station", "track_id", "total_played_seconds"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_TRACK_FINISHED_QUESTIONS = (
    VerificationQuestion(
        id="finished_target",
        text="Are station, track_id, and total_played_seconds correct for track finished?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("finished_call", "station", "track_id", "total_played_seconds"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_TRACK_STARTED_QUESTIONS = (
    VerificationQuestion(
        id="started_target",
        text="Are station and track_id correct for track started feedback?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("started_call", "station", "track_id"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_USERS_DISLIKES_ARTISTS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="artist_id_correct",
        text="Is artist_id the artist the user asked to mark «Не рекомендовать»?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("dislike_artist_add_call", "artist_id"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
    VerificationQuestion(
        id="add_not_remove",
        text="Did the user want to add a dislike, not remove it?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_DISLIKES_ARTISTS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="artist_id_correct",
        text="Is artist_id the artist whose dislike the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("dislike_artist_remove_call", "artist_id"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
)

YANDEX_MUSIC_USERS_DISLIKES_TRACKS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="track_ids_correct",
        text="Are track_ids the tracks the user asked to dislike/not recommend?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("dislike_tracks_add_call", "track_ids"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_USERS_DISLIKES_TRACKS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="track_ids_correct",
        text="Are track_ids the tracks whose dislike the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("dislike_tracks_remove_call", "track_ids"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_USERS_LIKES_ALBUMS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="album_ids_correct",
        text="Are album_ids the albums the user asked to like?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_albums_add_call", "album_ids"), _USER_GOAL, _PRIOR_YM_ALBUM),
    ),
    VerificationQuestion(
        id="like_not_unlike",
        text="Did the user want to add a like, not remove it?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_LIKES_ALBUMS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="album_ids_correct",
        text="Are album_ids the albums the user asked to unlike?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_albums_remove_call", "album_ids"), _USER_GOAL, _PRIOR_YM_ALBUM),
    ),
)

YANDEX_MUSIC_USERS_LIKES_ARTISTS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="artist_ids_correct",
        text="Are artist_ids the artists the user asked to like?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_artists_add_call", "artist_ids"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
    VerificationQuestion(
        id="like_not_unlike",
        text="Did the user want to add a like, not remove it?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_LIKES_ARTISTS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="artist_ids_correct",
        text="Are artist_ids the artists the user asked to unlike?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_artists_remove_call", "artist_ids"), _USER_GOAL, _PRIOR_YM_ARTIST),
    ),
)

YANDEX_MUSIC_USERS_LIKES_CLIPS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="clip_id_correct",
        text="Is clip_id the clip the user asked to like?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_clips_add_call", "clip_id"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_USERS_LIKES_CLIPS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="clip_id_correct",
        text="Is clip_id the clip the user asked to unlike?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_clips_remove_call", "clip_id"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_USERS_LIKES_PLAYLISTS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="playlist_ids_correct",
        text="Are playlist_ids the playlists the user asked to like?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_playlists_add_call", "playlist_ids"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_USERS_LIKES_PLAYLISTS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="playlist_ids_correct",
        text="Are playlist_ids the playlists the user asked to unlike?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_playlists_remove_call", "playlist_ids"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_USERS_LIKES_TRACKS_ADD_QUESTIONS = (
    VerificationQuestion(
        id="track_ids_correct",
        text="Are track_ids the tracks the user asked to add to «Мне нравится»?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_tracks_add_call", "track_ids"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
    VerificationQuestion(
        id="like_not_unlike",
        text="Did the user want to like, not unlike?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_LIKES_TRACKS_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="track_ids_correct",
        text="Are track_ids the tracks the user asked to remove from likes?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("likes_tracks_remove_call", "track_ids"), _USER_GOAL, _PRIOR_YM_TRACK),
    ),
)

YANDEX_MUSIC_USERS_PLAYLISTS_CHANGE_QUESTIONS = (
    VerificationQuestion(
        id="playlist_target",
        text="Are kind and diff the playlist changes the user requested?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("playlists_change_call", "kind", "diff", "revision"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_USERS_PLAYLISTS_CREATE_QUESTIONS = (
    VerificationQuestion(
        id="title_matches",
        text="Does title match the playlist name the user asked to create?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("playlists_create_call", "title", "visibility"), _USER_GOAL),
    ),
)

YANDEX_MUSIC_USERS_PLAYLISTS_DELETE_QUESTIONS = (
    VerificationQuestion(
        id="playlist_target",
        text="Is kind the playlist the user explicitly asked to delete?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("playlists_delete_call", "kind"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
    VerificationQuestion(
        id="delete_intent",
        text="Did the user explicitly ask to delete the whole playlist?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_PLAYLISTS_DELETE_TRACK_QUESTIONS = (
    VerificationQuestion(
        id="playlist_and_range",
        text="Are kind and to (track range) the tracks the user asked to remove from the playlist?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("delete_track_call", "kind", "from", "to", "revision"), _USER_GOAL, _PRIOR_YM_PLAYLIST),
    ),
    VerificationQuestion(
        id="delete_not_insert",
        text="Did the user want to remove tracks, not add them?",
        severity=SEVERITY_WARN,
        evidence=(_USER_GOAL,),
    ),
)

YANDEX_MUSIC_USERS_PLAYLISTS_INSERT_TRACK_QUESTIONS = (
    VerificationQuestion(
        id="track_and_playlist",
        text="Are kind, track_id, and album_id the track the user asked to add to the playlist?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("insert_track_call", "kind", "track_id", "album_id", "at"), _USER_GOAL, _PRIOR_YM_TRACK, _PRIOR_YM_PLAYLIST),
    ),
)

YANDEX_MUSIC_USERS_PRESAVES_ADD_QUESTIONS = (
    VerificationQuestion(
        id="album_id_correct",
        text="Is album_id the upcoming album the user asked to presave?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("presaves_add_call", "album_id", "like_after_release"), _USER_GOAL, _PRIOR_YM_ALBUM),
    ),
)

YANDEX_MUSIC_USERS_PRESAVES_REMOVE_QUESTIONS = (
    VerificationQuestion(
        id="album_id_correct",
        text="Is album_id the presaved album the user asked to remove?",
        severity=SEVERITY_CRITICAL,
        evidence=(_call("presaves_remove_call", "album_id"), _USER_GOAL, _PRIOR_YM_ALBUM),
    ),
)

MUSIC_CHECKER_QUESTIONS_BY_TOOL: dict[str, tuple[VerificationQuestion, ...]] = {
    "yandex.music.search": YANDEX_MUSIC_SEARCH_QUESTIONS,
    "yandex.music.search_suggest": YANDEX_MUSIC_SEARCH_SUGGEST_QUESTIONS,
    "yandex.music.tracks": YANDEX_MUSIC_TRACKS_QUESTIONS,
    "yandex.music.albums": YANDEX_MUSIC_ALBUMS_QUESTIONS,
    "yandex.music.albums_with_tracks": YANDEX_MUSIC_ALBUMS_WITH_TRACKS_QUESTIONS,
    "yandex.music.artists": YANDEX_MUSIC_ARTISTS_QUESTIONS,
    "yandex.music.artists_tracks": YANDEX_MUSIC_ARTISTS_TRACKS_QUESTIONS,
    "yandex.music.tracks_lyrics": YANDEX_MUSIC_TRACKS_LYRICS_QUESTIONS,
    "yandex.music.tracks_full_info": YANDEX_MUSIC_TRACKS_FULL_INFO_QUESTIONS,
    "yandex.music.playlist": YANDEX_MUSIC_PLAYLIST_QUESTIONS,
    "yandex.music.playlists": YANDEX_MUSIC_PLAYLISTS_QUESTIONS,
    "yandex.music.users_playlists_list": YANDEX_MUSIC_USERS_PLAYLISTS_LIST_QUESTIONS,
    "yandex.music.users_likes_tracks": YANDEX_MUSIC_USERS_LIKES_TRACKS_QUESTIONS,
    "yandex.music.users_likes_albums": YANDEX_MUSIC_USERS_LIKES_ALBUMS_QUESTIONS,
    "yandex.music.users_likes_artists": YANDEX_MUSIC_USERS_LIKES_ARTISTS_QUESTIONS,
    "yandex.music.feed": YANDEX_MUSIC_FEED_QUESTIONS,
    "yandex.music.playlists_personal": YANDEX_MUSIC_PLAYLISTS_PERSONAL_QUESTIONS,
    "yandex.music.rotor_station_tracks": YANDEX_MUSIC_ROTOR_STATION_TRACKS_QUESTIONS,
    "yandex.music.rotor_stations_dashboard": YANDEX_MUSIC_ROTOR_STATIONS_DASHBOARD_QUESTIONS,
    "yandex.music.music_history": YANDEX_MUSIC_MUSIC_HISTORY_QUESTIONS,
    "yandex.music.queue": YANDEX_MUSIC_QUEUE_QUESTIONS,
    "yandex.music.queues_list": YANDEX_MUSIC_QUEUES_LIST_QUESTIONS,
    "yandex.music.track_download": YANDEX_MUSIC_TRACK_DOWNLOAD_QUESTIONS,
    "yandex.music.account_settings_set": YANDEX_MUSIC_ACCOUNT_SETTINGS_SET_QUESTIONS,
    "yandex.music.consume_promo_code": YANDEX_MUSIC_CONSUME_PROMO_CODE_QUESTIONS,
    "yandex.music.pin_album": YANDEX_MUSIC_PIN_ALBUM_QUESTIONS,
    "yandex.music.pin_artist": YANDEX_MUSIC_PIN_ARTIST_QUESTIONS,
    "yandex.music.pin_playlist": YANDEX_MUSIC_PIN_PLAYLIST_QUESTIONS,
    "yandex.music.pin_wave": YANDEX_MUSIC_PIN_WAVE_QUESTIONS,
    "yandex.music.unpin_album": YANDEX_MUSIC_UNPIN_ALBUM_QUESTIONS,
    "yandex.music.unpin_artist": YANDEX_MUSIC_UNPIN_ARTIST_QUESTIONS,
    "yandex.music.unpin_playlist": YANDEX_MUSIC_UNPIN_PLAYLIST_QUESTIONS,
    "yandex.music.unpin_wave": YANDEX_MUSIC_UNPIN_WAVE_QUESTIONS,
    "yandex.music.play_audio": YANDEX_MUSIC_PLAY_AUDIO_QUESTIONS,
    "yandex.music.playlists_collective_join": YANDEX_MUSIC_PLAYLISTS_COLLECTIVE_JOIN_QUESTIONS,
    "yandex.music.queue_create": YANDEX_MUSIC_QUEUE_CREATE_QUESTIONS,
    "yandex.music.rotor_station_feedback": YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_QUESTIONS,
    "yandex.music.rotor_station_feedback_radio_started": YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_RADIO_STARTED_QUESTIONS,
    "yandex.music.rotor_station_feedback_skip": YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_SKIP_QUESTIONS,
    "yandex.music.rotor_station_feedback_track_finished": YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_TRACK_FINISHED_QUESTIONS,
    "yandex.music.rotor_station_feedback_track_started": YANDEX_MUSIC_ROTOR_STATION_FEEDBACK_TRACK_STARTED_QUESTIONS,
    "yandex.music.users_dislikes_artists_add": YANDEX_MUSIC_USERS_DISLIKES_ARTISTS_ADD_QUESTIONS,
    "yandex.music.users_dislikes_artists_remove": YANDEX_MUSIC_USERS_DISLIKES_ARTISTS_REMOVE_QUESTIONS,
    "yandex.music.users_dislikes_tracks_add": YANDEX_MUSIC_USERS_DISLIKES_TRACKS_ADD_QUESTIONS,
    "yandex.music.users_dislikes_tracks_remove": YANDEX_MUSIC_USERS_DISLIKES_TRACKS_REMOVE_QUESTIONS,
    "yandex.music.users_likes_albums_add": YANDEX_MUSIC_USERS_LIKES_ALBUMS_ADD_QUESTIONS,
    "yandex.music.users_likes_albums_remove": YANDEX_MUSIC_USERS_LIKES_ALBUMS_REMOVE_QUESTIONS,
    "yandex.music.users_likes_artists_add": YANDEX_MUSIC_USERS_LIKES_ARTISTS_ADD_QUESTIONS,
    "yandex.music.users_likes_artists_remove": YANDEX_MUSIC_USERS_LIKES_ARTISTS_REMOVE_QUESTIONS,
    "yandex.music.users_likes_clips_add": YANDEX_MUSIC_USERS_LIKES_CLIPS_ADD_QUESTIONS,
    "yandex.music.users_likes_clips_remove": YANDEX_MUSIC_USERS_LIKES_CLIPS_REMOVE_QUESTIONS,
    "yandex.music.users_likes_playlists_add": YANDEX_MUSIC_USERS_LIKES_PLAYLISTS_ADD_QUESTIONS,
    "yandex.music.users_likes_playlists_remove": YANDEX_MUSIC_USERS_LIKES_PLAYLISTS_REMOVE_QUESTIONS,
    "yandex.music.users_likes_tracks_add": YANDEX_MUSIC_USERS_LIKES_TRACKS_ADD_QUESTIONS,
    "yandex.music.users_likes_tracks_remove": YANDEX_MUSIC_USERS_LIKES_TRACKS_REMOVE_QUESTIONS,
    "yandex.music.users_playlists_change": YANDEX_MUSIC_USERS_PLAYLISTS_CHANGE_QUESTIONS,
    "yandex.music.users_playlists_create": YANDEX_MUSIC_USERS_PLAYLISTS_CREATE_QUESTIONS,
    "yandex.music.users_playlists_delete": YANDEX_MUSIC_USERS_PLAYLISTS_DELETE_QUESTIONS,
    "yandex.music.users_playlists_delete_track": YANDEX_MUSIC_USERS_PLAYLISTS_DELETE_TRACK_QUESTIONS,
    "yandex.music.users_playlists_insert_track": YANDEX_MUSIC_USERS_PLAYLISTS_INSERT_TRACK_QUESTIONS,
    "yandex.music.users_presaves_add": YANDEX_MUSIC_USERS_PRESAVES_ADD_QUESTIONS,
    "yandex.music.users_presaves_remove": YANDEX_MUSIC_USERS_PRESAVES_REMOVE_QUESTIONS,
}

MUSIC_CHECKER_ALL_TOOL_NAMES = tuple(MUSIC_CHECKER_QUESTIONS_BY_TOOL.keys())

MUSIC_CHECKER_TIER1_TOOL_NAMES = tuple(
    name
    for name in MUSIC_CHECKER_ALL_TOOL_NAMES
    if name
    in {
        "yandex.music.search",
        "yandex.music.search_suggest",
        "yandex.music.tracks",
        "yandex.music.albums",
        "yandex.music.albums_with_tracks",
        "yandex.music.artists",
        "yandex.music.artists_tracks",
        "yandex.music.tracks_lyrics",
        "yandex.music.tracks_full_info",
        "yandex.music.playlist",
        "yandex.music.playlists",
        "yandex.music.users_playlists_list",
        "yandex.music.users_likes_tracks",
        "yandex.music.users_likes_albums",
        "yandex.music.users_likes_artists",
        "yandex.music.feed",
        "yandex.music.playlists_personal",
        "yandex.music.rotor_station_tracks",
        "yandex.music.rotor_stations_dashboard",
        "yandex.music.music_history",
        "yandex.music.queue",
        "yandex.music.queues_list",
        "yandex.music.track_download",
    }
)

MUSIC_CHECKER_TIER2_TOOL_NAMES = tuple(
    name for name in MUSIC_CHECKER_ALL_TOOL_NAMES if name not in MUSIC_CHECKER_TIER1_TOOL_NAMES
)

MUSIC_CHECKER_READ_TOOL_NAMES = tuple(
    name for name in MUSIC_CHECKER_TIER1_TOOL_NAMES if name != "yandex.music.track_download"
)

MUSIC_CHECKER_WRITE_TOOL_NAMES = tuple(
    name
    for name in MUSIC_CHECKER_ALL_TOOL_NAMES
    if name == "yandex.music.track_download" or name in MUSIC_CHECKER_TIER2_TOOL_NAMES
)
