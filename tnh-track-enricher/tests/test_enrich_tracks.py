# tnh-track-enricher/tests/test_enrich_tracks.py
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# --- format_duration ---

def test_format_duration_exact_minutes():
    from enrich_tracks import format_duration
    assert format_duration(360.0) == "6:00"

def test_format_duration_with_seconds():
    from enrich_tracks import format_duration
    assert format_duration(402.5) == "6:42"

def test_format_duration_no_leading_zero_on_minutes():
    from enrich_tracks import format_duration
    assert format_duration(65.0) == "1:05"

def test_format_duration_zero_minutes():
    from enrich_tracks import format_duration
    assert format_duration(45.0) == "0:45"

def test_format_duration_rounds_down():
    from enrich_tracks import format_duration
    # truncates to whole seconds, does not round up
    assert format_duration(61.9) == "1:01"

# --- _strip_isrc_hyphens ---

def test_strip_isrc_hyphens_removes_all():
    from enrich_tracks import _strip_isrc_hyphens
    assert _strip_isrc_hyphens("GB-EWA-23-03320") == "GBEWA2303320"

def test_strip_isrc_hyphens_no_hyphens():
    from enrich_tracks import _strip_isrc_hyphens
    assert _strip_isrc_hyphens("GBEWA2303320") == "GBEWA2303320"

# --- _slugify ---

def test_slugify_spaces_to_hyphens():
    from enrich_tracks import _slugify
    assert _slugify("Lane 8") == "Lane-8"

def test_slugify_strips_special_chars():
    from enrich_tracks import _slugify
    assert _slugify("RnR (Lane 8 Remix)") == "RnR-Lane-8-Remix"

def test_slugify_collapses_double_hyphens():
    from enrich_tracks import _slugify
    # "Sultan + Shepard": spaces→hyphens → "Sultan-+-Shepard"
    # strip non-alnum/hyphen → "Sultan--Shepard"
    # collapse runs → "Sultan-Shepard"
    assert _slugify("Sultan + Shepard") == "Sultan-Shepard"

def test_slugify_three_artists_joined():
    from enrich_tracks import _slugify
    combined = "Lane 8 x Sultan + Shepard x sadhappy"
    assert _slugify(combined) == "Lane-8-x-Sultan-Shepard-x-sadhappy"

def test_slugify_no_trailing_hyphens():
    from enrich_tracks import _slugify
    result = _slugify("Track Name!")
    assert not result.endswith("-")
    assert not result.startswith("-")

# --- build_proposed_filename ---

def test_build_proposed_filename_single_artist_with_version():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GB-EWA-23-03320",
        artist_names=["Sultan + Shepard"],
        track_title="RnR (Lane 8 Remix)",
        version=["Remix"],
        original_filename="Sultan-Shepard-RnR-Lane-8-Remix-GBEWA2303320.flac",
    )
    assert result == "GBEWA2303320_Sultan-Shepard_RnR-Lane-8-Remix_Remix.flac"

def test_build_proposed_filename_three_artists():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8", "Sultan + Shepard", "sadhappy"],
        track_title="Disappear",
        version=["Extended Mix"],
        original_filename="Lane-8-x-S-S-x-sadhappy-Disappear-v19m.wav",
    )
    assert result == "GBTNHH2500001_Lane-8-x-Sultan-Shepard-x-sadhappy_Disappear_Extended-Mix.wav"

def test_build_proposed_filename_no_version():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8"],
        track_title="Disappear",
        version=[],
        original_filename="Lane-8-Disappear.wav",
    )
    assert result == "GBTNHH2500001_Lane-8_Disappear.wav"

def test_build_proposed_filename_uses_first_version_only():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8"],
        track_title="Disappear",
        version=["Extended Mix", "Radio Edit"],
        original_filename="Lane-8-Disappear.wav",
    )
    assert result == "GBTNHH2500001_Lane-8_Disappear_Extended-Mix.wav"

def test_build_proposed_filename_preserves_extension():
    from enrich_tracks import build_proposed_filename
    result = build_proposed_filename(
        isrc="GBTNHH2500001",
        artist_names=["Lane 8"],
        track_title="Disappear",
        version=["Extended Mix"],
        original_filename="track.aiff",
    )
    assert result.endswith(".aiff")

# --- filename_matches ---

def test_filename_matches_correct_format():
    from enrich_tracks import filename_matches
    assert filename_matches("GBEWA2303320_Sultan-Shepard_RnR_Remix.flac", "GB-EWA-23-03320") is True

def test_filename_matches_isrc_present_but_not_first():
    from enrich_tracks import filename_matches
    # ISRC appears but is not the first _ segment
    assert filename_matches("Sultan-Shepard-GBEWA2303320.flac", "GB-EWA-23-03320") is False

def test_filename_matches_no_isrc():
    from enrich_tracks import filename_matches
    assert filename_matches("Sultan-Shepard-Track.flac", "GB-EWA-23-03320") is False

def test_filename_matches_case_insensitive():
    from enrich_tracks import filename_matches
    assert filename_matches("gbewa2303320_Sultan-Shepard_Track.flac", "GB-EWA-23-03320") is True

def test_filename_matches_version_less():
    from enrich_tracks import filename_matches
    # Version-less correctly formatted file still matches
    assert filename_matches("GBTNHH2500001_Lane-8_Disappear.wav", "GBTNHH2500001") is True

# --- extract_dropbox_filename ---

def test_extract_dropbox_filename_standard_url():
    from enrich_tracks import extract_dropbox_filename
    url = "https://www.dropbox.com/scl/fi/abc123/Sultan-Shepard-Track.flac?rlkey=xyz&dl=0"
    assert extract_dropbox_filename(url) == "Sultan-Shepard-Track.flac"

def test_extract_dropbox_filename_wav():
    from enrich_tracks import extract_dropbox_filename
    url = "https://www.dropbox.com/scl/fi/abc123/Lane-8-Disappear.wav?rlkey=xyz&dl=0"
    assert extract_dropbox_filename(url) == "Lane-8-Disappear.wav"

# --- dropbox_direct_url ---

def test_dropbox_direct_url_converts_dl0_to_dl1():
    from enrich_tracks import dropbox_direct_url
    url = "https://www.dropbox.com/scl/fi/abc123/track.wav?rlkey=xyz&dl=0"
    assert dropbox_direct_url(url) == "https://www.dropbox.com/scl/fi/abc123/track.wav?rlkey=xyz&dl=1"
