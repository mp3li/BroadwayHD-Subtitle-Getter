#!/usr/bin/env python3
# Copyright (C) 2026 mp3li
# SPDX-License-Identifier: GPL-3.0-only

"""
BroadwayHD Subtitle Getter by mp3li.

This standalone tool signs into BroadwayHD in a hidden local Chrome session,
captures subtitle .vtt network calls from BroadwayHD detail pages, downloads
the subtitle files, converts them to .srt, and saves them either in a local
Subtitles folder or beside matched media folders.
"""

from __future__ import annotations

import base64
import copy
import dataclasses
import difflib
import getpass
import html
import json
import os
import re
import socket
import struct
import subprocess
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


WELCOME_MESSAGE = """
Welcome to BroadwayHD Subtitle Getter by mp3li

This tool signs into BroadwayHD in a hidden local Chrome session, searches BroadwayHD detail pages for subtitle .vtt network calls, downloads the subtitle files, converts them to .srt, and saves them either in the Subtitles folder or beside matched media folders.
"""

NAME = "BroadwayHD Subtitle Getter by mp3li"
MY_LINKS_DIR_NAME = "My Links Txt"
MY_LINKS_FILE_NAME = "mylinks.txt"
SETTINGS_DIR_NAME = "Settings"
SETTINGS_FILE_NAME = "settings.json"
MARKER_FILE_NAME = ".broadwayhd-item.json"
CHROME_APP_PATH = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 "
    "mp3li-broadwayhd-subtitle-getter/1.0"
)
API_BASE = "https://dce-frontoffice.imggaming.com"
API_KEY = "857a1e5d-e35e-4fdf-805b-a87b6f8364bf"
DEFAULT_REALM = "dce.bhd"
INIT_QUERY = (
    "lk=language&pk=subTitleLanguage&pk=subtitlePreferenceMode&"
    "pk=subtitlePreferenceMap&pk=audioLanguage&pk=autoAdvance&"
    "pk=pluginAccessTokens&pk=videoBackgroundAutoPlay&readLicences=true&"
    "countEvents=LIVE&menuTargetPlatform=MOBILE-WEB&readIconStore=ENABLED&"
    "readUserProfiles=true&altMenuTargetPlatform=WEB"
)
PAGE_HOSTS = {"broadwayhd.com", "www.broadwayhd.com"}
VIDEO_FILE_EXTENSIONS = {
    ".3gp",
    ".avi",
    ".flv",
    ".m2ts",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mts",
    ".ts",
    ".webm",
    ".wmv",
}
DEFAULT_SETTINGS: dict[str, Any] = {
    "output_dir": "Subtitles",
    "browser": {
        "profile_dir": "Browser Session/Chrome Profile",
        "capture_timeout_seconds": 45,
        "login_timeout_seconds": 60,
        "quiet_seconds_after_first_vtt": 3,
    },
    "subtitle_preferences": {
        "mode": "all",
        "preferred_languages": ["en-US", "en-GB", "en"],
        "fallback_to_all": True,
        "save_vtt": False,
        "save_srt": True,
    },
    "media_matching": {
        "enabled": False,
        "media_roots": [],
        "save_to_matched_media_folder": True,
        "rename_matched_folders": False,
        "match_threshold": 0.88,
        "scan_subfolders": True,
    },
}


@dataclass
class LoginCredentials:
    email: str = ""
    password: str = ""


@dataclass
class ChromeDebugEndpoint:
    port: int = 0
    browser_websocket_url: str = ""


@dataclass
class BroadwayHDSession:
    realm: str
    token: str

    @property
    def auth_headers(self) -> dict[str, str]:
        headers = default_headers()
        headers["Realm"] = self.realm
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers


@dataclass
class BroadwayHDSubtitleMetadata:
    source_url: str = ""
    detail_link: str = ""
    item_id: str = ""
    title: str = ""
    subtitle_languages: list[str] = field(default_factory=list)

    @property
    def playback_url(self) -> str:
        separator = "&" if "?" in self.source_url else "?"
        return f"{self.source_url}{separator}t=0"


@dataclass
class SubtitleFile:
    language: str
    url: str
    vtt_path: Path | None = None
    srt_path: Path | None = None


@dataclass
class MediaMatch:
    folder: Path
    filename_base: str
    matched_name: str
    score: float
    source: str


@dataclass
class SubtitleSaveTarget:
    folder: Path
    base_name: str
    write_marker: bool = False


@dataclass
class SubtitleSaveResult:
    title: str
    folder: Path
    files: list[Path]


class UnsupportedProviderError(ValueError):
    pass


class AnimatedStatus:
    def __init__(self, message: str) -> None:
        self.message = message

    def __enter__(self) -> "AnimatedStatus":
        print(self.message)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def log_step(message: str) -> None:
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}")


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def mylinks_path() -> Path:
    return project_root() / MY_LINKS_DIR_NAME / MY_LINKS_FILE_NAME


def settings_path() -> Path:
    return project_root() / SETTINGS_DIR_NAME / SETTINGS_FILE_NAME


def load_settings() -> dict[str, Any]:
    path = settings_path()
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    if not path.exists():
        return settings
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is not valid JSON: {error}") from error
    except OSError as error:
        raise ValueError(f"Could not read {path}: {error}") from error
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return merge_settings(settings, loaded)


def merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merge_settings(base[key], value)
        else:
            base[key] = value
    return base


def settings_section(settings: dict[str, Any], name: str) -> dict[str, Any]:
    value = settings.get(name)
    if isinstance(value, dict):
        return value
    default_value = DEFAULT_SETTINGS.get(name)
    return copy.deepcopy(default_value) if isinstance(default_value, dict) else {}


def settings_bool(settings: dict[str, Any], section_name: str, key: str, default: bool) -> bool:
    section = settings_section(settings, section_name)
    value = section.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes", "y", "1", "on"}:
            return True
        if lowered in {"false", "no", "n", "0", "off"}:
            return False
    return default


def settings_float(settings: dict[str, Any], section_name: str, key: str, default: float) -> float:
    section = settings_section(settings, section_name)
    try:
        value = float(section.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, value))


def settings_int(settings: dict[str, Any], section_name: str, key: str, default: int) -> int:
    section = settings_section(settings, section_name)
    try:
        value = int(section.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(1, value)


def resolve_configured_path(value: Any, default_relative_path: str) -> Path:
    text = str(value).strip() if value is not None else ""
    if not text:
        text = default_relative_path
    path = Path(os.path.expanduser(text))
    if not path.is_absolute():
        path = project_root() / path
    return path


def configured_output_dir(settings: dict[str, Any]) -> Path:
    return resolve_configured_path(settings.get("output_dir"), "Subtitles")


def configured_browser_profile_dir(settings: dict[str, Any]) -> Path:
    section = settings_section(settings, "browser")
    return resolve_configured_path(section.get("profile_dir"), "Browser Session/Chrome Profile")


def configured_media_roots(settings: dict[str, Any]) -> list[Path]:
    section = settings_section(settings, "media_matching")
    roots = section.get("media_roots", [])
    if isinstance(roots, (str, Path)):
        roots = [roots]
    if not isinstance(roots, list):
        return []
    paths: list[Path] = []
    seen: set[str] = set()
    for value in roots:
        text = str(value).strip()
        if not text:
            continue
        path = resolve_configured_path(text, "")
        key = str(path)
        if key not in seen:
            paths.append(path)
            seen.add(key)
    return paths


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    text = html.unescape(str(value))
    text = re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)
    text = "".join(
        " " if ch in "\r\n\t" else ch
        for ch in text
        if unicodedata.category(ch) not in {"Cc", "Cf", "Cs", "Co", "Cn"}
    )
    return text.strip()


def safe_filename(name: str) -> str:
    cleaned = clean_text(name)
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = re.sub(r"^[-_ ]+(?=[A-Za-z0-9])", "", cleaned)
    return cleaned[:120].strip(" .") or "subtitle"


def normalize_media_match_text(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text.casefold())
    return re.sub(r"\s+", " ", text).strip()


def comparable_url(value: str) -> str:
    return clean_text(value).rstrip("/")


def is_http_url(value: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def clean_url_from_text(value: str) -> str:
    url = clean_text(value).strip("<>")
    url = url.rstrip(".,;")
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]
    while url.endswith("]") and url.count("[") < url.count("]"):
        url = url[:-1]
    return url


def extract_urls_from_text(value: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"https?://\S+", value):
        url = clean_url_from_text(match.group(0))
        if is_http_url(url):
            urls.append(url)
    return urls


def load_mylinks_entries() -> list[str]:
    path = mylinks_path()
    if not path.exists():
        raise ValueError(f"Could not find {path}.")
    lines = path.read_text(encoding="utf-8").splitlines()
    urls: list[str] = []
    block: list[str] = []
    for line in lines:
        if line.strip():
            block.append(line.strip())
            continue
        urls.extend(urls_from_block(block))
        block = []
    urls.extend(urls_from_block(block))
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        key = comparable_url(url)
        if key not in seen:
            deduped.append(url)
            seen.add(key)
    return deduped


def urls_from_block(block: list[str]) -> list[str]:
    urls: list[str] = []
    for line in block:
        urls.extend(extract_urls_from_text(line))
    return urls


def ask_required_yes_no(prompt: str) -> bool:
    while True:
        answer = input(f"{prompt} [Y/N]: ").strip().casefold()
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please type Y or N.")


def choose_input_mode() -> str:
    print("Would you like to import your mylinks.txt or manually insert links here?")
    print("1. Import your mylinks.txt")
    print("2. Manually insert links here")
    while True:
        answer = input("Choose 1 or 2: ").strip()
        if answer == "1":
            return "import"
        if answer == "2":
            return "manual"
        print("Please type 1 or 2.")


def get_link_from_user() -> str:
    while True:
        link = input("Paste your detail page link: ").strip()
        if not link:
            print("Please paste a link before continuing.")
            continue
        return link


def get_links_from_user() -> list[str]:
    links: list[str] = []
    while True:
        links.append(get_link_from_user())
        if not ask_required_yes_no("Would you like to paste another link?"):
            return links


def prompt_login_credentials() -> LoginCredentials:
    print("\nBroadwayHD Sign-In\n")
    print("This tool uses a hidden local Chrome session.")
    print("Your password is only used for this run and is not written to settings.json.")
    print("If your saved browser session still works, you can press Enter and skip typing credentials.\n")
    email = input("BroadwayHD email (press Enter to reuse saved session): ").strip()
    if not email:
        return LoginCredentials()
    password = getpass.getpass("BroadwayHD password: ").strip()
    return LoginCredentials(email=email, password=password)


def is_broadwayhd_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    return parsed.netloc.casefold() in PAGE_HOSTS


def video_id_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(clean_text(url))
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] == "video" and parts[1].isdigit():
        return parts[1]
    return ""


def ensure_supported_url(url: str) -> None:
    if not is_broadwayhd_url(url) or not video_id_from_url(url):
        raise UnsupportedProviderError(
            "Unfortunately this tool only supports BroadwayHD detail page links right now."
        )


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://broadwayhd.com",
        "Referer": "https://broadwayhd.com/",
        "x-api-key": API_KEY,
        "x-app": "dice-web",
    }


def fetch_text(url: str, headers: dict[str, str], timeout: int) -> str:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace")
    except Exception:
        return fetch_text_with_curl(url, headers=headers, timeout=timeout)


def fetch_text_with_curl(url: str, headers: dict[str, str], timeout: int) -> str:
    command = [
        "/usr/bin/curl",
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--compressed",
        "--max-time",
        str(timeout),
    ]
    for name, value in headers.items():
        if name.casefold() == "user-agent":
            command.extend(["--user-agent", value])
        else:
            command.extend(["--header", f"{name}: {value}"])
    command.append(url)
    result = subprocess.run(command, capture_output=True, check=False, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"curl exited with {result.returncode}")
    return result.stdout


def fetch_json(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    text = fetch_text(url, headers=headers, timeout=timeout)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("BroadwayHD API returned an unexpected response.")
    return data


def nested_value(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for part in path:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def fetch_session(timeout: int) -> BroadwayHDSession:
    log_step("Requesting BroadwayHD session token...")
    init = fetch_json(
        f"{API_BASE}/api/v1/init/?{INIT_QUERY}",
        headers=default_headers(),
        timeout=timeout,
    )
    realm = clean_text(nested_value(init, ("settings", "realm"))) or DEFAULT_REALM
    token = clean_text(nested_value(init, ("authentication", "authorisationToken")))
    log_step(f"BroadwayHD session ready. Realm: {realm}. Token present: {'yes' if bool(token) else 'no'}.")
    return BroadwayHDSession(realm=realm, token=token)


def extract_metadata(url: str, timeout: int = 25) -> BroadwayHDSubtitleMetadata:
    item_id = video_id_from_url(url)
    if not item_id:
        raise ValueError("BroadwayHD links need a /video/ ID.")
    log_step(f"Extracting subtitle metadata for BroadwayHD item {item_id}...")
    session = fetch_session(timeout=timeout)
    vod = fetch_json(
        f"{API_BASE}/api/v4/vod/{item_id}?includePlaybackDetails=URL",
        headers=session.auth_headers,
        timeout=timeout,
    )
    title = clean_text(vod.get("title")) or f"BroadwayHD video {item_id}"
    subtitle_languages: list[str] = []
    for item in nested_value(vod, ("onlinePlaybackMetadata", "subtitles")) or []:
        if not isinstance(item, dict):
            continue
        language = normalize_language_tag(item.get("languageTag"))
        if language and language not in subtitle_languages:
            subtitle_languages.append(language)
    log_step(
        f"Metadata loaded. Title: {title}. API subtitle languages: "
        f"{', '.join(subtitle_languages) if subtitle_languages else 'none listed'}."
    )
    return BroadwayHDSubtitleMetadata(
        source_url=f"https://broadwayhd.com/video/{item_id}",
        detail_link=url,
        item_id=item_id,
        title=title,
        subtitle_languages=subtitle_languages,
    )


def normalize_language_tag(value: Any) -> str:
    text = clean_text(value).replace("_", "-")
    parts = [part for part in text.split("-") if part]
    if not parts:
        return ""
    normalized: list[str] = []
    for index, part in enumerate(parts):
        normalized.append(part.lower() if index == 0 else part.upper())
    return "-".join(normalized)


def language_from_vtt_url(url: str) -> str:
    match = re.search(r"subtitle-([A-Za-z]{2}(?:[-_][A-Za-z]{2})?)", url)
    if match:
        return normalize_language_tag(match.group(1))
    return "und"


def subtitle_mode(settings: dict[str, Any]) -> str:
    section = settings_section(settings, "subtitle_preferences")
    mode = clean_text(section.get("mode", "all")).casefold()
    return mode if mode in {"all", "preferred"} else "all"


def preferred_languages(settings: dict[str, Any]) -> list[str]:
    section = settings_section(settings, "subtitle_preferences")
    values = section.get("preferred_languages", [])
    if isinstance(values, str):
        values = [values]
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        language = normalize_language_tag(value)
        if language and language not in seen:
            output.append(language)
            seen.add(language)
    return output


def filter_subtitle_urls(urls: list[str], settings: dict[str, Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    if subtitle_mode(settings) == "all":
        return deduped

    wanted = preferred_languages(settings)
    matches = [url for url in deduped if language_from_vtt_url(url) in wanted]
    if matches:
        return matches
    if settings_bool(settings, "subtitle_preferences", "fallback_to_all", True):
        return deduped
    return []


def find_media_match(title: str, settings: dict[str, Any]) -> MediaMatch | None:
    if not settings_bool(settings, "media_matching", "enabled", False):
        return None
    roots = configured_media_roots(settings)
    if not roots:
        return None
    targets = [normalize_media_match_text(title), normalize_media_match_text(safe_filename(title))]
    targets = [target for target in targets if target]
    if not targets:
        return None
    threshold = settings_float(settings, "media_matching", "match_threshold", 0.88)
    recursive = settings_bool(settings, "media_matching", "scan_subfolders", True)
    best_match: MediaMatch | None = None
    for root in roots:
        for candidate in iter_media_match_candidates(root, recursive):
            match = media_match_for_candidate(candidate, targets)
            if not match or match.score < threshold:
                continue
            if is_better_media_match(match, best_match):
                best_match = match
    return best_match


def iter_media_match_candidates(root: Path, recursive: bool) -> Iterator[Path]:
    if not root.exists():
        return
    if root.is_file():
        if root.suffix.casefold() in VIDEO_FILE_EXTENSIONS:
            yield root
        return
    if not root.is_dir():
        return
    yield root
    iterator = root.rglob("*") if recursive else root.iterdir()
    for path in iterator:
        if should_skip_media_candidate(path):
            continue
        if path.is_dir() or path.suffix.casefold() in VIDEO_FILE_EXTENSIONS:
            yield path


def should_skip_media_candidate(path: Path) -> bool:
    ignored_names = {"extras", "gallery", "trailers", "videos", "__pycache__", "subtitles"}
    return path.name.startswith(".") or path.name.casefold() in ignored_names


def media_match_for_candidate(path: Path, targets: list[str]) -> MediaMatch | None:
    source = "file" if path.is_file() else "folder"
    candidate_name = path.stem if path.is_file() else path.name
    candidate = normalize_media_match_text(candidate_name)
    if not candidate:
        return None
    score = max(media_match_score(candidate, target) for target in targets)
    if score <= 0:
        return None
    return MediaMatch(
        folder=path.parent if path.is_file() else path,
        filename_base=path.stem if path.is_file() else path.name,
        matched_name=candidate_name,
        score=score,
        source=source,
    )


def media_match_score(candidate: str, target: str) -> float:
    if not candidate or not target:
        return 0.0
    if candidate == target:
        return 1.0
    ratio = difflib.SequenceMatcher(None, candidate, target).ratio()
    if candidate in target or target in candidate:
        length_ratio = min(len(candidate), len(target)) / max(len(candidate), len(target))
        if length_ratio >= 0.65:
            ratio = max(ratio, 0.93)
    return ratio


def is_better_media_match(match: MediaMatch, current: MediaMatch | None) -> bool:
    if current is None:
        return True
    if match.score != current.score:
        return match.score > current.score
    source_priority = {"file": 2, "folder": 1}
    return source_priority.get(match.source, 0) > source_priority.get(current.source, 0)


def output_folder_for_title(title: str, settings: dict[str, Any]) -> Path:
    match = find_media_match(title, settings)
    if match and settings_bool(settings, "media_matching", "save_to_matched_media_folder", True):
        log_step(f"Matched existing media folder for subtitles: {match.folder}")
        return match.folder
    target = configured_output_dir(settings) / safe_filename(title)
    log_step(f"No media folder match found. Using subtitle output folder: {target}")
    return target


def ensure_unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    index = 2
    while True:
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def folder_marker_path(folder: Path) -> Path:
    return folder / MARKER_FILE_NAME


def read_folder_marker_item_id(folder: Path) -> str:
    path = folder_marker_path(folder)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(data, dict):
        return ""
    return clean_text(data.get("item_id"))


def find_existing_marked_output_folder(output_root: Path, item_id: str) -> Path | None:
    if not item_id or not output_root.exists():
        return None
    try:
        for folder in output_root.iterdir():
            if not folder.is_dir():
                continue
            if read_folder_marker_item_id(folder) == item_id:
                return folder
    except OSError:
        return None
    return None


def write_folder_marker(folder: Path, metadata: BroadwayHDSubtitleMetadata) -> None:
    path = folder_marker_path(folder)
    payload = {
        "provider": "BroadwayHD",
        "item_id": metadata.item_id,
        "title": metadata.title,
        "detail_link": metadata.detail_link,
        "source_url": metadata.source_url,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def folder_has_numbered_subtitle_duplicates(folder: Path) -> bool:
    try:
        for path in folder.iterdir():
            if not path.is_file():
                continue
            if path.suffix.casefold() not in {".srt", ".vtt"}:
                continue
            if re.search(r"-\d+\.(?:srt|vtt)$", path.name, flags=re.IGNORECASE):
                return True
    except OSError:
        return False
    return False


def disambiguated_metadata_title(metadata: BroadwayHDSubtitleMetadata) -> str:
    return f"{metadata.title} ({metadata.item_id})"


def resolve_save_target(
    metadata: BroadwayHDSubtitleMetadata,
    settings: dict[str, Any],
) -> SubtitleSaveTarget:
    match = find_media_match(metadata.title, settings)
    if match and settings_bool(settings, "media_matching", "save_to_matched_media_folder", True):
        log_step(f"Matched existing media folder for subtitles: {match.folder}")
        return SubtitleSaveTarget(folder=match.folder, base_name=match.filename_base, write_marker=False)

    output_root = configured_output_dir(settings)
    existing_marked_folder = find_existing_marked_output_folder(output_root, metadata.item_id)
    if existing_marked_folder is not None:
        log_step(f"Reusing existing BroadwayHD subtitle folder for item {metadata.item_id}: {existing_marked_folder}")
        return SubtitleSaveTarget(
            folder=existing_marked_folder,
            base_name=safe_filename(metadata.title),
            write_marker=True,
        )
    title = metadata.title
    target = output_root / safe_filename(title)
    if target.exists():
        marker_item_id = read_folder_marker_item_id(target)
        needs_disambiguation = (
            (marker_item_id and marker_item_id != metadata.item_id)
            or (not marker_item_id and folder_has_numbered_subtitle_duplicates(target))
        )
        if needs_disambiguation:
            title = disambiguated_metadata_title(metadata)
            target = output_root / safe_filename(title)
    log_step(f"No media folder match found. Using subtitle output folder: {target}")
    return SubtitleSaveTarget(folder=target, base_name=safe_filename(title), write_marker=True)


def subtitle_download_headers() -> dict[str, str]:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Referer": "https://broadwayhd.com/",
        "Origin": "https://broadwayhd.com",
    }


def download_url_to_file(url: str, path: Path, timeout: int = 30) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    log_step(f"Downloading: {url}")
    request = urllib.request.Request(url, headers=subtitle_download_headers())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except Exception:
        log_step("Direct download failed in Python. Retrying with curl...")
        command = [
            "/usr/bin/curl",
            "--location",
            "--fail",
            "--silent",
            "--show-error",
            "--compressed",
            "--max-time",
            str(timeout),
            "--user-agent",
            USER_AGENT,
            "--header",
            "Accept: */*",
            "--header",
            "Referer: https://broadwayhd.com/",
            "--header",
            "Origin: https://broadwayhd.com",
            url,
        ]
        result = subprocess.run(command, capture_output=True, check=False, timeout=timeout + 10)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(stderr or f"curl exited with {result.returncode}")
        data = result.stdout
    path.write_bytes(data)
    log_step(f"Saved file: {path}")
    return path


def vtt_to_srt_text(vtt_text: str) -> str:
    text = vtt_text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip("\n") for block in re.split(r"\n{2,}", text) if block.strip()]
    cues: list[str] = []
    index = 1
    for block in blocks:
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines:
            continue
        header = lines[0].strip()
        if header.startswith("WEBVTT") or header.startswith("NOTE") or header.startswith("STYLE") or header.startswith("REGION") or header.startswith("X-TIMESTAMP-MAP"):
            continue
        timestamp_index = 0
        if "-->" not in lines[0] and len(lines) >= 2 and "-->" in lines[1]:
            timestamp_index = 1
        if "-->" not in lines[timestamp_index]:
            continue
        timestamp = normalize_srt_timestamp_line(lines[timestamp_index])
        payload = lines[timestamp_index + 1 :]
        if not payload:
            payload = [""]
        cues.append(str(index))
        cues.append(timestamp)
        cues.extend(payload)
        cues.append("")
        index += 1
    return "\n".join(cues).strip() + ("\n" if cues else "")


def normalize_srt_timestamp_line(line: str) -> str:
    left, right = [part.strip() for part in line.split("-->", 1)]
    return f"{normalize_srt_timestamp(left)} --> {normalize_srt_timestamp(right)}"


def normalize_srt_timestamp(value: str) -> str:
    match = re.match(r"(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{3})", value)
    if not match:
        return value.replace(".", ",")
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4))
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def save_subtitles(
    metadata: BroadwayHDSubtitleMetadata,
    subtitle_urls: list[str],
    settings: dict[str, Any],
) -> SubtitleSaveResult:
    target = resolve_save_target(metadata, settings)
    target_dir = target.folder
    target_dir.mkdir(parents=True, exist_ok=True)
    log_step(f"Saving subtitles for {metadata.title} into {target_dir}")
    files: list[Path] = []
    for url in subtitle_urls:
        language = language_from_vtt_url(url)
        base_name = f"{target.base_name}.{language}"
        log_step(f"Preparing subtitle language {language} from {url}")
        if settings_bool(settings, "subtitle_preferences", "save_vtt", False):
            vtt_path = ensure_unique_output_path(target_dir / f"{base_name}.vtt")
            download_url_to_file(url, vtt_path)
            files.append(vtt_path)
        else:
            vtt_path = None

        if settings_bool(settings, "subtitle_preferences", "save_srt", True):
            if vtt_path and vtt_path.exists():
                vtt_text = vtt_path.read_text(encoding="utf-8", errors="replace")
            else:
                vtt_text = fetch_text(url, headers=subtitle_download_headers(), timeout=30)
            srt_text = vtt_to_srt_text(vtt_text)
            srt_path = ensure_unique_output_path(target_dir / f"{base_name}.srt")
            srt_path.write_text(srt_text, encoding="utf-8")
            files.append(srt_path)
            log_step(f"Saved converted SRT: {srt_path}")
    if target.write_marker:
        try:
            write_folder_marker(target_dir, metadata)
        except OSError:
            pass
    return SubtitleSaveResult(title=metadata.title, folder=target_dir, files=files)


def browser_timeout(settings: dict[str, Any], key: str, default: int) -> int:
    return settings_int(settings, "browser", key, default)


def quiet_seconds_after_first_vtt(settings: dict[str, Any]) -> int:
    return settings_int(settings, "browser", "quiet_seconds_after_first_vtt", 3)


def browser_profile_dir(settings: dict[str, Any]) -> Path:
    path = configured_browser_profile_dir(settings)
    path.mkdir(parents=True, exist_ok=True)
    return path


def js_string(value: str) -> str:
    return json.dumps(value)


def login_interaction_script(email: str, password: str) -> str:
    return f"""
(() => {{
  const haveCredentials = {json.dumps(bool(email and password))};
  const visible = (el) => !!el && !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const textOf = (el) => ((el && (el.innerText || el.textContent || el.value || el.getAttribute('aria-label') || '')) || '').trim();
  const compactText = (el) => textOf(el).replace(/\\s+/g, ' ').trim();
  const shortLabel = (el) => compactText(el).split(/\\n+/)[0].trim();
  const setValue = (input, value) => {{
    if (!input) return;
    const prototype = Object.getPrototypeOf(input);
    const descriptor = prototype ? Object.getOwnPropertyDescriptor(prototype, 'value') : null;
    if (descriptor && descriptor.set) {{
      descriptor.set.call(input, value);
    }} else {{
      input.value = value;
    }}
    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
    input.dispatchEvent(new Event('blur', {{ bubbles: true }}));
  }};
  const interactiveNodes = () => Array.from(document.querySelectorAll(
    'button,[role=button],input[type=submit],a,[tabindex],div[role=button],span[role=button]'
  )).filter((node) => visible(node));
  const bestMatchingNode = (pattern) => {{
    const candidates = interactiveNodes()
      .map((node) => {{
        const fullText = compactText(node);
        const label = shortLabel(node);
        if (!pattern.test(fullText) && !pattern.test(label)) return null;
        let score = 0;
        if (pattern.test(label)) score += 1000;
        if (label.length <= 24) score += 500;
        if (label.length <= 12) score += 250;
        if (node.tagName === 'BUTTON') score += 400;
        if (node.tagName === 'A') score += 200;
        if ((node.getAttribute && node.getAttribute('role') === 'button')) score += 250;
        if (node.tagName === 'INPUT') score += 300;
        if (/^play$|^watch$|^watch now$|^sign in$|^log in$|^continue$|^submit$/i.test(label)) score += 700;
        score -= Math.min(fullText.length, 400);
        return [node, score];
      }})
      .filter(Boolean)
      .sort((left, right) => right[1] - left[1]);
    return candidates.length ? candidates[0][0] : null;
  }};
  const collectVttCandidates = () => {{
    const found = new Set();
    const addFromText = (value) => {{
      const text = String(value || '');
      const matches = text.match(/https?:\\/\\/[^\\s"'<>]+\\.vtt[^\\s"'<>]*/gi) || [];
      for (const match of matches) {{
        found.add(match.replace(/[),.;]+$/, ''));
      }}
    }};
    try {{
      for (const entry of performance.getEntriesByType('resource')) {{
        addFromText(entry && entry.name);
      }}
    }} catch (_error) {{}}
    try {{
      addFromText(document.documentElement ? document.documentElement.outerHTML : '');
    }} catch (_error) {{}}
    try {{
      for (const script of Array.from(document.scripts || [])) {{
        addFromText(script.textContent || '');
        addFromText(script.src || '');
      }}
    }} catch (_error) {{}}
    try {{
      for (const track of Array.from(document.querySelectorAll('track'))) {{
        addFromText(track.src || track.getAttribute('src') || '');
      }}
    }} catch (_error) {{}}
    try {{
      addFromText(window.__NEXT_DATA__ ? JSON.stringify(window.__NEXT_DATA__) : '');
    }} catch (_error) {{}}
    try {{
      addFromText(window.__INITIAL_STATE__ ? JSON.stringify(window.__INITIAL_STATE__) : '');
    }} catch (_error) {{}}
    return Array.from(found);
  }};
  const clickByText = (pattern) => {{
    const target = bestMatchingNode(pattern);
    if (target) {{
      target.click();
      return shortLabel(target) || compactText(target) || target.tagName;
    }}
    return '';
  }};
  const clickInterstitialCta = () => {{
    if (!/\\/interstitial\\//i.test(location.href)) return '';
    const target = bestMatchingNode(/watch now|play|watch|resume|continue|start|stream|enter|proceed|go/i);
    if (target) {{
      target.click();
      return shortLabel(target) || compactText(target) || target.tagName || 'clicked interstitial cta';
    }}
    return '';
  }};
  const wakePlayerControls = () => {{
    const video = document.querySelector('video');
    if (!video) return false;
    const rect = video.getBoundingClientRect ? video.getBoundingClientRect() : {{ left: 10, top: 10, width: 40, height: 40 }};
    const clientX = rect.left + Math.max(10, Math.min(rect.width || 40, 30));
    const clientY = rect.top + Math.max(10, Math.min(rect.height || 40, 30));
    for (const type of ['mousemove', 'mouseover', 'mouseenter', 'pointermove']) {{
      video.dispatchEvent(new MouseEvent(type, {{ bubbles: true, cancelable: true, clientX, clientY }}));
    }}
    return true;
  }};
  const clickSubtitleToggle = () => {{
    wakePlayerControls();
    const selectorCandidates = Array.from(document.querySelectorAll(
      '[aria-label],[title],[data-testid],[data-test-id],button,[role=button],span[role=button],div[role=button]'
    )).filter((node) => visible(node));
    for (const node of selectorCandidates) {{
      const haystack = [
        compactText(node),
        node.getAttribute('aria-label') || '',
        node.getAttribute('title') || '',
        node.getAttribute('data-testid') || '',
        node.getAttribute('data-test-id') || ''
      ].join(' ');
      if (/\\bcc\\b|caption|subtitle/i.test(haystack)) {{
        node.click();
        return shortLabel(node) || compactText(node) || node.getAttribute('aria-label') || node.tagName || 'subtitle control';
      }}
    }}
    return clickByText(/\\bcc\\b|caption|subtitle/i);
  }};
  const dismiss = clickByText(/accept|agree|allow all|allow cookies/i);
  const inputs = Array.from(document.querySelectorAll('input'));
  const emailInput = inputs.find((input) => visible(input) && (/email/i.test(input.type || '') || /email/i.test(input.name || '') || /email/i.test(input.placeholder || '') || /email/i.test(input.getAttribute('aria-label') || '')));
  const passwordInput = inputs.find((input) => visible(input) && ((input.type || '').toLowerCase() === 'password' || /password/i.test(input.name || '') || /password/i.test(input.placeholder || '') || /password/i.test(input.getAttribute('aria-label') || '')));
  const submitLoginForm = () => {{
    if (!passwordInput) return '';
    const form = passwordInput.form || passwordInput.closest('form');
    if (form) {{
      const submitNode = Array.from(form.querySelectorAll('button,input[type=submit],[role=button]'))
        .find((node) => visible(node) && /sign in|log in|login|continue|submit/i.test(textOf(node) || node.value || ''));
      if (submitNode) {{
        submitNode.click();
        return textOf(submitNode) || submitNode.value || 'submitted form button';
      }}
      if (typeof form.requestSubmit === 'function') {{
        form.requestSubmit();
        return 'requestSubmit';
      }}
      form.dispatchEvent(new Event('submit', {{ bubbles: true, cancelable: true }}));
      return 'submit event';
    }}
    const passwordRect = passwordInput.getBoundingClientRect ? passwordInput.getBoundingClientRect() : {{ top: 0, left: 0 }};
    const nearby = interactiveNodes()
      .map((node) => {{
        const rect = node.getBoundingClientRect ? node.getBoundingClientRect() : {{ top: 99999, left: 99999 }};
        const distance = Math.abs(rect.top - passwordRect.top) + Math.abs(rect.left - passwordRect.left);
        return [node, distance];
      }})
      .filter(([node]) => /sign in|log in|login|continue|submit/i.test(textOf(node)))
      .sort((left, right) => left[1] - right[1]);
    const target = nearby.length ? nearby[0][0] : null;
    if (target) {{
      target.click();
      return textOf(target) || target.tagName || 'submitted nearby button';
    }}
    return '';
  }};
  const pageText = textOf(document.body);
  const purchaseDetected = /purchase|buy now|subscribe|free trial|start your free trial/i.test(pageText);
  const playDetected = /watch now|resume|continue watching|play/i.test(pageText);
  let state = 'ready';
  let submitClick = '';
  if (emailInput && !passwordInput) {{
    state = 'email-step';
    emailInput.focus();
    setValue(emailInput, {js_string(email)});
    clickByText(/continue|next|sign in|login|log in/i);
  }} else if (emailInput && passwordInput) {{
    state = 'login-form';
    emailInput.focus();
    setValue(emailInput, {js_string(email)});
    passwordInput.focus();
    setValue(passwordInput, {js_string(password)});
    submitClick = submitLoginForm();
    state = 'submitted';
  }}
  const signInClick = (!emailInput || !passwordInput) && haveCredentials && purchaseDetected
    ? clickByText(/sign in|log in|login|my account|account/i)
    : '';
  if (signInClick) {{
    state = 'needs-login';
  }}
  const interstitialClick = !signInClick && (!purchaseDetected || playDetected || !haveCredentials)
    ? clickInterstitialCta()
    : '';
  if (interstitialClick) {{
    state = 'interstitial';
  }}
  const watchClick = clickByText(/watch now|watch|play|resume|continue|trailer/i);
  const subtitleClick = playDetected ? clickSubtitleToggle() : '';
  return {{
    href: location.href,
    title: document.title,
    state,
    dismissed: dismiss,
    purchaseDetected,
    playDetected,
    signInClick,
    submitClick,
    interstitialClick,
    watchClick,
    subtitleClick,
    vttCandidates: collectVttCandidates()
  }};
}})()
"""


def runtime_evaluate(websocket: "DevToolsWebSocket", next_id: int, expression: str) -> int:
    websocket.send_json(
        {
            "id": next_id,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
            },
        }
    )
    return next_id + 1


def extract_runtime_value(message: dict[str, Any]) -> Any:
    result = nested_value(message, ("result", "result", "value"))
    return result


def subtitle_candidates_from_cdp_message(message: dict[str, Any]) -> list[str]:
    method = message.get("method", "")
    params = message.get("params", {})
    candidates: list[str] = []
    if method == "Network.requestWillBeSent":
        candidates.append((params.get("request") or {}).get("url", ""))
    elif method == "Network.responseReceived":
        candidates.append((params.get("response") or {}).get("url", ""))
    elif method == "Network.responseReceivedExtraInfo":
        candidates.append(params.get("url", ""))
    return [candidate for candidate in candidates if ".vtt" in candidate.casefold()]


def subtitle_candidates_from_runtime_value(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    candidates = value.get("vttCandidates")
    if not isinstance(candidates, list):
        return []
    output: list[str] = []
    for candidate in candidates:
        text = clean_text(candidate)
        if text and ".vtt" in text.casefold() and text not in output:
            output.append(text)
    return output


def is_auth_like_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(clean_text(url))
    host = parsed.netloc.casefold()
    path = parsed.path.casefold()
    if host and "broadwayhd.com" not in host:
        return True
    auth_bits = ("login", "log-in", "signin", "sign-in", "signup", "sign-up", "register")
    return any(bit in path for bit in auth_bits)


def wait_for_chrome_debugging_endpoint(
    profile_path: Path,
    process: subprocess.Popen,
    started_at: float,
) -> ChromeDebugEndpoint:
    active_port_path = profile_path / "DevToolsActivePort"
    deadline = time.time() + 10
    while time.time() < deadline:
        if process.poll() is not None:
            return ChromeDebugEndpoint()
        if active_port_path.exists():
            try:
                stat = active_port_path.stat()
            except OSError:
                time.sleep(0.1)
                continue
            if stat.st_mtime + 0.01 < started_at:
                time.sleep(0.1)
                continue
            lines = active_port_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if lines and lines[0].isdigit():
                port = int(lines[0])
                browser_websocket_url = ""
                if len(lines) >= 2 and lines[1].startswith("/"):
                    browser_websocket_url = f"ws://127.0.0.1:{port}{lines[1]}"
                return ChromeDebugEndpoint(port=port, browser_websocket_url=browser_websocket_url)
        time.sleep(0.1)
    return ChromeDebugEndpoint()


def create_chrome_devtools_page(port: int) -> str:
    log_step(f"Opening Chrome DevTools page on debugging port {port}...")
    deadline = time.time() + 10
    while time.time() < deadline:
        for method in ("PUT", "GET"):
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/json/new",
                    method=method,
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
                websocket_url = data.get("webSocketDebuggerUrl", "")
                if websocket_url:
                    log_step("Chrome DevTools page created.")
                    return websocket_url
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
                continue
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as response:
                pages = json.loads(response.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pages = []
        for page in pages:
            websocket_url = page.get("webSocketDebuggerUrl", "")
            if websocket_url:
                log_step("Reusing existing Chrome DevTools page.")
                return websocket_url
        time.sleep(0.25)
    log_step("Chrome DevTools page could not be opened before timeout.")
    return ""


class DevToolsWebSocket:
    def __init__(self, websocket_url: str) -> None:
        parsed = urllib.parse.urlparse(websocket_url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        self.path = parsed.path
        if parsed.query:
            self.path += "?" + parsed.query
        self.sock: socket.socket | None = None

    def connect(self, startup_timeout: float = 10.0) -> None:
        deadline = time.time() + startup_timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            sock: socket.socket | None = None
            try:
                sock = socket.create_connection((self.host, self.port), timeout=2)
                request = (
                    f"GET {self.path} HTTP/1.1\r\n"
                    f"Host: {self.host}:{self.port}\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    "Sec-WebSocket-Version: 13\r\n"
                    "\r\n"
                )
                sock.sendall(request.encode("ascii"))
                response = b""
                while b"\r\n\r\n" not in response:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    response += chunk
                if b" 101 " not in response.split(b"\r\n", 1)[0]:
                    raise RuntimeError("Chrome DevTools WebSocket handshake failed.")
                self.sock = sock
                return
            except (ConnectionRefusedError, OSError, RuntimeError) as error:
                last_error = error
                if sock:
                    sock.close()
                time.sleep(0.2)
        if last_error:
            raise last_error
        raise RuntimeError("Chrome DevTools WebSocket could not be opened.")

    def send_json(self, payload: dict[str, Any]) -> None:
        self.send_text(json.dumps(payload, separators=(",", ":")))

    def send_text(self, text: str) -> None:
        if not self.sock:
            return
        payload = text.encode("utf-8")
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length <= 0xFFFF:
            header.extend([0x80 | 126])
            header.extend(struct.pack("!H", length))
        else:
            header.extend([0x80 | 127])
            header.extend(struct.pack("!Q", length))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + mask + masked)

    def recv_json(self, timeout: float = 1) -> dict[str, Any] | None:
        text = self.recv_text(timeout=timeout)
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def recv_text(self, timeout: float = 1) -> str:
        if not self.sock:
            return ""
        self.sock.settimeout(timeout)
        try:
            first_two = self.read_exact(2)
        except (TimeoutError, socket.timeout):
            return ""
        if len(first_two) < 2:
            return ""
        opcode = first_two[0] & 0x0F
        masked = bool(first_two[1] & 0x80)
        length = first_two[1] & 0x7F
        if length == 126:
            length = struct.unpack("!H", self.read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self.read_exact(8))[0]
        mask = self.read_exact(4) if masked else b""
        payload = self.read_exact(length)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode in {8, 9} or opcode != 1:
            return ""
        return payload.decode("utf-8", errors="replace")

    def read_exact(self, size: int) -> bytes:
        if not self.sock:
            return b""
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self.sock.recv(size - len(chunks))
            if not chunk:
                break
            chunks.extend(chunk)
        return bytes(chunks)

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None


def send_cdp_command(
    websocket: DevToolsWebSocket,
    next_id: int,
    method: str,
    params: dict[str, Any] | None = None,
    session_id: str = "",
) -> int:
    payload: dict[str, Any] = {
        "id": next_id,
        "method": method,
        "params": params or {},
    }
    if session_id:
        payload["sessionId"] = session_id
    websocket.send_json(payload)
    return next_id + 1


def wait_for_cdp_result(
    websocket: DevToolsWebSocket,
    command_id: int,
    timeout_seconds: int,
    session_id: str = "",
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        message = websocket.recv_json(timeout=1)
        if not message or message.get("id") != command_id:
            continue
        message_session = clean_text(message.get("sessionId"))
        if session_id and message_session and message_session != session_id:
            continue
        return message
    raise RuntimeError(f"Timed out waiting for DevTools response to command {command_id}.")


def connect_browser_target_session(browser_websocket_url: str) -> tuple[DevToolsWebSocket, str]:
    log_step(f"Connecting to browser-level DevTools WebSocket: {browser_websocket_url}")
    websocket = DevToolsWebSocket(browser_websocket_url)
    log_step("Waiting for browser-level DevTools socket to accept connections...")
    websocket.connect()
    try:
        next_id = 1
        create_id = next_id
        next_id = send_cdp_command(
            websocket,
            next_id,
            "Target.createTarget",
            {"url": "about:blank"},
        )
        create_response = wait_for_cdp_result(websocket, create_id, 10)
        target_id = clean_text(nested_value(create_response, ("result", "targetId")))
        if not target_id:
            raise RuntimeError("Chrome did not return a target ID for subtitle capture.")
        log_step(f"Created DevTools target: {target_id}")

        attach_id = next_id
        next_id = send_cdp_command(
            websocket,
            next_id,
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )
        attach_response = wait_for_cdp_result(websocket, attach_id, 10)
        session_id = clean_text(nested_value(attach_response, ("result", "sessionId")))
        if not session_id:
            raise RuntimeError("Chrome did not return a target session for subtitle capture.")
        log_step(f"Attached to DevTools target session: {session_id}")
        return websocket, session_id
    except Exception:
        websocket.close()
        raise


def capture_subtitle_urls(
    detail_page_url: str,
    login: LoginCredentials,
    settings: dict[str, Any],
) -> list[str]:
    if not CHROME_APP_PATH.exists():
        raise RuntimeError("Google Chrome is not installed at /Applications/Google Chrome.app.")
    profile_path = browser_profile_dir(settings)
    log_step(f"Using Chrome profile: {profile_path}")
    log_step(
        "Starting hidden Chrome for subtitle capture "
        f"({'saved session only' if not (login.email and login.password) else 'saved session plus login credentials'})..."
    )
    active_port_path = profile_path / "DevToolsActivePort"
    if active_port_path.exists():
        try:
            active_port_path.unlink()
            log_step("Removed stale Chrome DevToolsActivePort file from previous run.")
        except OSError:
            log_step("Could not remove stale DevToolsActivePort file. Waiting for a fresh one anyway.")
    command = [
        str(CHROME_APP_PATH),
        "--headless=new",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-default-apps",
        "--disable-sync",
        "--mute-audio",
        "--no-first-run",
        "--no-default-browser-check",
        "--autoplay-policy=no-user-gesture-required",
        "--remote-debugging-port=0",
        f"--user-data-dir={profile_path}",
        f"--user-agent={USER_AGENT}",
        "about:blank",
    ]
    started_at = time.time()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        endpoint = wait_for_chrome_debugging_endpoint(profile_path, process, started_at)
        if not endpoint.port:
            raise RuntimeError("Could not start hidden Chrome for subtitle capture.")
        log_step(f"Hidden Chrome is running. DevTools port: {endpoint.port}")
        if endpoint.browser_websocket_url:
            log_step(f"Browser DevTools WebSocket: {endpoint.browser_websocket_url}")
            websocket, session_id = connect_browser_target_session(endpoint.browser_websocket_url)
            return watch_chrome_network_for_subtitles(
                websocket,
                detail_page_url,
                login,
                settings,
                session_id=session_id,
            )
        log_step("Browser-level DevTools WebSocket was not present. Falling back to page discovery.")
        websocket_url = create_chrome_devtools_page(endpoint.port)
        if not websocket_url:
            raise RuntimeError("Could not open a Chrome DevTools page for subtitle capture.")
        websocket = DevToolsWebSocket(websocket_url)
        websocket.connect()
        return watch_chrome_network_for_subtitles(websocket, detail_page_url, login, settings)
    finally:
        log_step("Stopping hidden Chrome session.")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def watch_chrome_network_for_subtitles(
    websocket: DevToolsWebSocket,
    detail_page_url: str,
    login: LoginCredentials,
    settings: dict[str, Any],
    session_id: str = "",
) -> list[str]:
    try:
        next_id = 1
        for method, params in (
            ("Network.enable", {}),
            ("Page.enable", {}),
            ("Runtime.enable", {}),
            (
                "Network.setUserAgentOverride",
                {
                    "userAgent": USER_AGENT,
                    "acceptLanguage": "en-US,en;q=0.9",
                    "platform": "MacIntel",
                },
            ),
            ("Page.navigate", {"url": detail_page_url}),
        ):
            next_id = send_cdp_command(websocket, next_id, method, params, session_id=session_id)
        log_step(f"Navigated hidden Chrome to detail page: {detail_page_url}")

        capture_deadline = time.time() + browser_timeout(settings, "capture_timeout_seconds", 45)
        login_deadline = time.time() + browser_timeout(settings, "login_timeout_seconds", 60)
        last_action_at = 0.0
        found: list[str] = []
        found_at = 0.0
        navigated_back = False
        last_runtime_summary = ""
        while time.time() < capture_deadline:
            message = websocket.recv_json(timeout=1)
            message_session = clean_text(message.get("sessionId")) if message else ""
            if session_id and message and message_session and message_session != session_id:
                continue
            if message:
                for candidate in subtitle_candidates_from_cdp_message(message):
                    if candidate not in found:
                        found.append(candidate)
                        found_at = time.time()
                        log_step(f"Found subtitle URL from network event: {candidate}")
            if found and time.time() - found_at >= quiet_seconds_after_first_vtt(settings):
                log_step("Subtitle capture quiet period reached. Finishing capture.")
                break

            if time.time() <= login_deadline and time.time() - last_action_at >= 2:
                log_step("Running page interaction pass for cookies/login/watch buttons...")
                next_id = send_cdp_command(
                    websocket,
                    next_id,
                    "Runtime.evaluate",
                    {
                        "expression": login_interaction_script(login.email, login.password),
                        "returnByValue": True,
                        "awaitPromise": True,
                    },
                    session_id=session_id,
                )
                last_action_at = time.time()

            if message and "id" in message and message["id"] == next_id - 1 and (not session_id or not message_session or message_session == session_id):
                value = extract_runtime_value(message)
                for candidate in subtitle_candidates_from_runtime_value(value):
                    if candidate not in found:
                        found.append(candidate)
                        found_at = time.time()
                        log_step(f"Found subtitle URL from page state: {candidate}")
                href = clean_text((value or {}).get("href")) if isinstance(value, dict) else ""
                state = clean_text((value or {}).get("state")) if isinstance(value, dict) else ""
                dismissed = clean_text((value or {}).get("dismissed")) if isinstance(value, dict) else ""
                purchase_detected = bool((value or {}).get("purchaseDetected")) if isinstance(value, dict) else False
                play_detected = bool((value or {}).get("playDetected")) if isinstance(value, dict) else False
                sign_in_click = clean_text((value or {}).get("signInClick")) if isinstance(value, dict) else ""
                submit_click = clean_text((value or {}).get("submitClick")) if isinstance(value, dict) else ""
                interstitial_click = clean_text((value or {}).get("interstitialClick")) if isinstance(value, dict) else ""
                watch_click = clean_text((value or {}).get("watchClick")) if isinstance(value, dict) else ""
                subtitle_click = clean_text((value or {}).get("subtitleClick")) if isinstance(value, dict) else ""
                runtime_summary = f"state={state or 'unknown'} href={href or 'unknown'}"
                if runtime_summary != last_runtime_summary:
                    extras = []
                    if purchase_detected:
                        extras.append("purchase-detected")
                    if play_detected:
                        extras.append("play-detected")
                    if dismissed:
                        extras.append(f"cookie/clicked: {dismissed}")
                    if sign_in_click:
                        extras.append(f"signin/clicked: {sign_in_click}")
                    if submit_click:
                        extras.append(f"submit/clicked: {submit_click}")
                    if interstitial_click:
                        extras.append(f"interstitial/clicked: {interstitial_click}")
                    if watch_click:
                        extras.append(f"watch/clicked: {watch_click}")
                    if subtitle_click:
                        extras.append(f"subtitles/clicked: {subtitle_click}")
                    extra_text = f" ({'; '.join(extras)})" if extras else ""
                    log_step(f"Page interaction result: {runtime_summary}{extra_text}")
                    last_runtime_summary = runtime_summary
                if href and href != detail_page_url and state != "login-form" and not navigated_back and is_auth_like_url(href):
                    log_step(f"Browser moved to auth page {href}. Sending it back to the detail page.")
                    next_id = send_cdp_command(
                        websocket,
                        next_id,
                        "Page.navigate",
                        {"url": detail_page_url},
                        session_id=session_id,
                    )
                    navigated_back = True

        if found:
            log_step(f"Subtitle capture finished with {len(found)} subtitle URL(s).")
            return found
        log_step("Subtitle capture finished with no subtitle URLs found.")
        if login.email and login.password:
            raise RuntimeError("No subtitle .vtt network calls were captured after sign-in.")
        raise RuntimeError(
            "No subtitle .vtt network calls were captured. A saved login session may be required."
        )
    finally:
        websocket.close()


def save_for_link(
    url: str,
    login: LoginCredentials,
    settings: dict[str, Any],
) -> SubtitleSaveResult:
    ensure_supported_url(url)
    metadata = extract_metadata(url, timeout=25)
    log_step(f"Starting subtitle capture workflow for {metadata.title}")
    capture_targets = [url]
    if comparable_url(metadata.playback_url) not in {comparable_url(candidate) for candidate in capture_targets}:
        capture_targets.append(metadata.playback_url)
    captured_urls: list[str] = []
    last_error: Exception | None = None
    with AnimatedStatus("Loading... Searching for subtitles..."):
        for index, capture_target in enumerate(capture_targets, start=1):
            if index > 1:
                log_step(f"Retrying subtitle capture using playback URL: {capture_target}")
            try:
                captured_urls = capture_subtitle_urls(capture_target, login, settings)
                if captured_urls:
                    break
            except Exception as error:
                last_error = error
                if "No subtitle .vtt network calls were captured" not in str(error):
                    raise
        if not captured_urls and last_error:
            raise last_error
    log_step(f"Captured {len(captured_urls)} raw subtitle URL(s).")
    filtered_urls = filter_subtitle_urls(captured_urls, settings)
    log_step(f"{len(filtered_urls)} subtitle URL(s) remain after language filtering.")
    for kept_url in filtered_urls:
        log_step(f"Keeping subtitle URL: {kept_url}")
    if not filtered_urls:
        raise RuntimeError("Subtitle requests were captured, but none matched the current subtitle settings.")
    return save_subtitles(metadata, filtered_urls, settings)


def summarize_results(results: list[SubtitleSaveResult]) -> str:
    folder_count = len(results)
    file_count = sum(len(result.files) for result in results)
    return f"\nDone. Saved {folder_count} folder(s) with {file_count} subtitle item(s) total."


def process_links(links: list[str], login: LoginCredentials, settings: dict[str, Any]) -> int:
    results: list[SubtitleSaveResult] = []
    for link in links:
        print(f"\nChecking {link} ...")
        try:
            result = save_for_link(link, login, settings)
        except Exception as error:
            print(f"Could not get subtitles for {link}: {error}")
            continue
        results.append(result)
        print(f"Saved subtitles for {result.title} -> {result.folder}")
    print(summarize_results(results))
    return 0


def main() -> int:
    try:
        settings = load_settings()
    except ValueError as error:
        print(f"Could not load {SETTINGS_FILE_NAME}: {error}")
        return 1
    configured_output_dir(settings).mkdir(parents=True, exist_ok=True)
    print(WELCOME_MESSAGE, end="")
    login = prompt_login_credentials()
    mode = choose_input_mode()
    if mode == "import":
        try:
            links = load_mylinks_entries()
        except ValueError as error:
            print(error)
            return 1
    else:
        links = get_links_from_user()
    return process_links(links, login, settings)


if __name__ == "__main__":
    raise SystemExit(main())
