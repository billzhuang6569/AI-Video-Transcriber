import asyncio
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional


MEDIA_EXTENSIONS = frozenset({
    ".aac",
    ".flac",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".opus",
    ".ts",
    ".wav",
    ".webm",
})

PLATFORM_PAGE_HOSTS = {
    "youtube": ("youtube.com", "youtu.be"),
    "bilibili": ("bilibili.com", "b23.tv"),
    "douyin": ("douyin.com", "v.douyin.com", "iesdouyin.com"),
}

DIRECT_MEDIA_HOSTS = {
    "youtube": ("googlevideo.com",),
    "bilibili": ("bilivideo.com",),
    "douyin": ("douyinvod.com", "bytevcloud.com", "bytecdn.cn", "bytecdn.com"),
}

PLATFORM_REFERERS = {
    "youtube": "https://www.youtube.com/",
    "bilibili": "https://www.bilibili.com/",
    "douyin": "https://www.douyin.com/",
}


@dataclass(frozen=True)
class MediaSource:
    input_url: str
    resolved_url: str
    platform: str
    input_kind: str
    strategy: str
    prefer_subtitles: bool
    title: str = ""
    referer: str = ""
    content_type: str = ""


@dataclass(frozen=True)
class MediaProbe:
    is_direct_media: bool
    resolved_url: str
    content_type: str = ""


@dataclass(frozen=True)
class TikHubMedia:
    url: str
    video_id: str = ""
    content_type: str = ""


def _host_matches(host: str, candidates: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    return any(host == candidate or host.endswith(f".{candidate}") for candidate in candidates)


def _platform_for_host(host: str) -> str:
    for platform, candidates in DIRECT_MEDIA_HOSTS.items():
        if _host_matches(host, candidates):
            return platform
    for platform, candidates in PLATFORM_PAGE_HOSTS.items():
        if _host_matches(host, candidates):
            return platform
    return "generic"


def _is_known_direct_host(host: str) -> bool:
    return any(_host_matches(host, candidates) for candidates in DIRECT_MEDIA_HOSTS.values())


def _is_media_extension(url: str) -> bool:
    path = urllib.parse.urlparse(url).path
    return Path(urllib.parse.unquote(path)).suffix.lower() in MEDIA_EXTENSIONS


def _is_direct_url_hint(url: str, host: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return (
        _is_media_extension(url)
        or _is_known_direct_host(host)
        or "/aweme/v1/play/" in path
        or "/video/tos/" in path
    )


def _validate_http_url(url: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must be an absolute http or https URL")
    return parsed


def _derive_title(url: str, platform: str) -> str:
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path).rstrip("/")
    name = Path(path).stem if path else ""
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._-")
    return name[:80] or f"{platform}_media"


def _extract_tikhub_media(payload: Any) -> TikHubMedia:
    if not isinstance(payload, dict):
        raise ValueError("TikHub returned a non-object response")

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    url = data.get("original_video_url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("TikHub response did not contain data.original_video_url")

    media_url = url.strip()
    _validate_http_url(media_url)
    return TikHubMedia(
        url=media_url,
        video_id=str(data.get("video_id") or ""),
        content_type=str(data.get("content_type") or ""),
    )


class TikHubClient:
    def __init__(
        self,
        api_token: Optional[str] = None,
        base_url: Optional[str] = None,
        region: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
    ):
        self.api_token = (api_token or os.getenv("TIKHUB_API_TOKEN") or "").strip()
        self.base_url = (
            base_url
            or os.getenv("TIKHUB_BASE_URL")
            or "https://api.tikhub.io"
        ).rstrip("/")
        self.region = (region or os.getenv("TIKHUB_REGION") or "CN").strip().upper()
        self.timeout_seconds = timeout_seconds or int(os.getenv("TIKHUB_TIMEOUT_SECONDS", "120"))

    @property
    def is_configured(self) -> bool:
        return bool(self.api_token)

    async def resolve_douyin(self, share_url: str) -> TikHubMedia:
        if not self.is_configured:
            raise ValueError(
                "Douyin page URLs require TIKHUB_API_TOKEN; direct media URLs do not require TikHub"
            )
        return await asyncio.to_thread(self._resolve_douyin_sync, share_url)

    def _resolve_douyin_sync(self, share_url: str) -> TikHubMedia:
        query = urllib.parse.urlencode({"share_url": share_url, "region": self.region})
        endpoint = (
            f"{self.base_url}/api/v1/douyin/web/"
            f"fetch_video_high_quality_play_url?{query}"
        )
        request = urllib.request.Request(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "User-Agent": "AI-Video-Transcriber/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace").strip()
            raise ValueError(f"TikHub request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"TikHub request failed: {exc.reason}") from exc
        return _extract_tikhub_media(payload)


class MediaSourceResolver:
    def __init__(self, tikhub_client: Optional[TikHubClient] = None, probe_timeout_seconds: int = 15):
        self.tikhub_client = tikhub_client or TikHubClient()
        self.probe_timeout_seconds = probe_timeout_seconds

    async def resolve(self, url: str, prefer_subtitles: bool = True) -> MediaSource:
        input_url = url.strip()
        parsed = _validate_http_url(input_url)
        host = parsed.hostname or ""
        platform = _platform_for_host(host)

        if _is_direct_url_hint(input_url, host):
            return self._direct_source(input_url, input_url, platform)

        if platform == "douyin":
            media = await self.tikhub_client.resolve_douyin(input_url)
            title = f"douyin_{media.video_id}" if media.video_id else "douyin_video"
            return MediaSource(
                input_url=input_url,
                resolved_url=media.url,
                platform="douyin",
                input_kind="platform_page",
                strategy="douyin_tikhub_direct",
                prefer_subtitles=False,
                title=title,
                referer=input_url,
                content_type=media.content_type,
            )

        if platform in {"youtube", "bilibili"}:
            suffix = "subtitle_first" if prefer_subtitles else "audio_download"
            return MediaSource(
                input_url=input_url,
                resolved_url=input_url,
                platform=platform,
                input_kind="platform_page",
                strategy=f"{platform}_cookies_{suffix}",
                prefer_subtitles=prefer_subtitles,
                referer=PLATFORM_REFERERS[platform],
            )

        probe = await asyncio.to_thread(self._probe_direct_media, input_url)
        if probe.is_direct_media:
            resolved_platform = _platform_for_host(
                urllib.parse.urlparse(probe.resolved_url).hostname or ""
            )
            source = self._direct_source(input_url, probe.resolved_url, resolved_platform)
            return replace(source, content_type=probe.content_type)

        suffix = "subtitle_first" if prefer_subtitles else "audio_download"
        return MediaSource(
            input_url=input_url,
            resolved_url=probe.resolved_url or input_url,
            platform="generic",
            input_kind="platform_page",
            strategy=f"generic_{suffix}",
            prefer_subtitles=prefer_subtitles,
        )

    def _direct_source(self, input_url: str, resolved_url: str, platform: str) -> MediaSource:
        return MediaSource(
            input_url=input_url,
            resolved_url=resolved_url,
            platform=platform,
            input_kind="direct_media",
            strategy="direct_media_download",
            prefer_subtitles=False,
            title=_derive_title(resolved_url, platform),
            referer=PLATFORM_REFERERS.get(platform, ""),
        )

    def _probe_direct_media(self, url: str) -> MediaProbe:
        request = urllib.request.Request(
            url,
            headers={
                "Range": "bytes=0-1023",
                "Accept": "video/*,audio/*,application/octet-stream;q=0.8,*/*;q=0.1",
                "User-Agent": "Mozilla/5.0 (compatible; AI-Video-Transcriber/1.0)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.probe_timeout_seconds) as response:
                content_type = response.headers.get_content_type().lower()
                resolved_url = response.geturl() or url
                disposition = (response.headers.get("Content-Disposition") or "").lower()
                is_direct = (
                    content_type.startswith("video/")
                    or content_type.startswith("audio/")
                    or content_type == "application/octet-stream"
                    or any(ext in disposition for ext in MEDIA_EXTENSIONS)
                    or _is_media_extension(resolved_url)
                    or _is_known_direct_host(urllib.parse.urlparse(resolved_url).hostname or "")
                )
                return MediaProbe(is_direct, resolved_url, content_type)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
            return MediaProbe(False, url, "")
