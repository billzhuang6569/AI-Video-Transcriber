import sys
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import main as app_main  # noqa: E402
from media_source import (  # noqa: E402
    MediaProbe,
    MediaSource,
    MediaSourceResolver,
    TikHubMedia,
)


class FakeTikHubClient:
    def __init__(self):
        self.calls = []

    async def resolve_douyin(self, share_url):
        self.calls.append(share_url)
        return TikHubMedia(
            url="https://v5-ali-northeast.douyinvod.com/media/no-extension",
            video_id="7512756548356492544",
            content_type="video/mp4",
        )


class MediaSourceResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_youtube_and_bilibili_pages_use_cookie_subtitle_strategy(self):
        resolver = MediaSourceResolver(tikhub_client=FakeTikHubClient())

        youtube = await resolver.resolve("https://www.youtube.com/watch?v=abc123")
        bilibili = await resolver.resolve("https://b23.tv/example")

        self.assertEqual(youtube.platform, "youtube")
        self.assertEqual(youtube.input_kind, "platform_page")
        self.assertEqual(youtube.strategy, "youtube_cookies_subtitle_first")
        self.assertTrue(youtube.prefer_subtitles)
        self.assertEqual(bilibili.platform, "bilibili")
        self.assertEqual(bilibili.strategy, "bilibili_cookies_subtitle_first")

    async def test_douyin_page_resolves_through_tikhub(self):
        client = FakeTikHubClient()
        resolver = MediaSourceResolver(tikhub_client=client)
        source_url = "https://v.douyin.com/example/"

        source = await resolver.resolve(source_url)

        self.assertEqual(client.calls, [source_url])
        self.assertEqual(source.platform, "douyin")
        self.assertEqual(source.input_kind, "platform_page")
        self.assertEqual(source.strategy, "douyin_tikhub_direct")
        self.assertFalse(source.prefer_subtitles)
        self.assertEqual(source.content_type, "video/mp4")
        self.assertIn("douyinvod.com", source.resolved_url)

    async def test_direct_media_urls_skip_platform_page_resolution(self):
        client = FakeTikHubClient()
        resolver = MediaSourceResolver(tikhub_client=client)

        mp4 = await resolver.resolve("https://cdn.example.com/video.mp4?token=abc")
        douyin_cdn = await resolver.resolve(
            "https://v5-ali-northeast.douyinvod.com/media/no-extension"
        )
        douyin_play = await resolver.resolve(
            "https://www.douyin.com/aweme/v1/play/?video_id=123"
        )

        self.assertEqual(mp4.input_kind, "direct_media")
        self.assertEqual(mp4.strategy, "direct_media_download")
        self.assertEqual(douyin_cdn.platform, "douyin")
        self.assertEqual(douyin_cdn.input_kind, "direct_media")
        self.assertEqual(douyin_play.input_kind, "direct_media")
        self.assertEqual(client.calls, [])

    async def test_extensionless_generic_media_uses_content_type_probe(self):
        resolver = MediaSourceResolver(tikhub_client=FakeTikHubClient())
        with patch.object(
            resolver,
            "_probe_direct_media",
            return_value=MediaProbe(
                True,
                "https://cdn.example.com/signed-resource",
                "video/mp4",
            ),
        ):
            source = await resolver.resolve("https://cdn.example.com/signed-resource")

        self.assertEqual(source.input_kind, "direct_media")
        self.assertEqual(source.content_type, "video/mp4")

    async def test_non_http_input_is_rejected(self):
        resolver = MediaSourceResolver(tikhub_client=FakeTikHubClient())
        with self.assertRaisesRegex(ValueError, "absolute http or https"):
            await resolver.resolve("file:///tmp/video.mp4")


class TranscribeStrategyIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolved_direct_media_skips_subtitles_and_uses_resolved_url(self):
        task_id = str(uuid.uuid4())
        source = MediaSource(
            input_url="https://v.douyin.com/example/",
            resolved_url="https://v5-ali-northeast.douyinvod.com/media/no-extension",
            platform="douyin",
            input_kind="platform_page",
            strategy="douyin_tikhub_direct",
            prefer_subtitles=False,
            title="douyin_123",
            referer="https://v.douyin.com/example/",
            content_type="video/mp4",
        )
        request_transcriber = SimpleNamespace(
            provider="elevenlabs",
            model="scribe_v2",
            transcribe=AsyncMock(
                return_value=(
                    "# Video Transcription\n\n"
                    "**Detected Language:** zh\n\n"
                    "## Transcription Content\n\nhello"
                )
            ),
            get_detected_language=Mock(return_value="zh"),
        )
        app_main.tasks[task_id] = {
            "kind": "transcribe_url",
            "status": "processing",
            "progress": 0,
            "message": "created",
            "source_url": source.input_url,
        }

        try:
            with (
                patch.object(
                    app_main.media_source_resolver,
                    "resolve",
                    new=AsyncMock(return_value=source),
                ),
                patch.object(
                    app_main.video_processor,
                    "fetch_subtitles",
                    new=AsyncMock(),
                ) as subtitle_mock,
                patch.object(
                    app_main.video_processor,
                    "download_and_convert",
                    new=AsyncMock(return_value=("/tmp/nonexistent-test-audio.m4a", "Douyin title")),
                ) as download_mock,
                patch.object(app_main, "_build_request_transcriber", return_value=request_transcriber),
                patch.object(app_main, "save_tasks"),
            ):
                await app_main.process_transcribe_url_task(
                    task_id,
                    app_main.TranscribeUrlRequest(
                        url=source.input_url,
                        transcription_provider="elevenlabs",
                    ),
                )

            subtitle_mock.assert_not_awaited()
            download_mock.assert_awaited_once_with(
                source.resolved_url,
                app_main.TEMP_DIR,
                prefetched_title=source.title,
                referer=source.referer,
            )
            self.assertEqual(app_main.tasks[task_id]["status"], "completed")
            self.assertEqual(app_main.tasks[task_id]["platform"], "douyin")
            self.assertEqual(app_main.tasks[task_id]["input_kind"], "platform_page")
            self.assertEqual(app_main.tasks[task_id]["strategy"], "douyin_tikhub_direct")
            self.assertEqual(app_main.tasks[task_id]["resolved_url"], source.resolved_url)
            response = app_main._build_transcribe_url_task_response(
                task_id,
                app_main.tasks[task_id],
            )
            response_source = response["data"]["source"]
            self.assertEqual(response_source["url"], source.input_url)
            self.assertEqual(response_source["resolved_url"], source.resolved_url)
            self.assertEqual(response_source["platform"], "douyin")
            self.assertEqual(response_source["input_kind"], "platform_page")
            self.assertEqual(response_source["strategy"], "douyin_tikhub_direct")
        finally:
            app_main.tasks.pop(task_id, None)
            app_main.active_tasks.pop(task_id, None)

    async def test_frontend_video_task_uses_the_same_direct_media_strategy(self):
        task_id = str(uuid.uuid4())
        source = MediaSource(
            input_url="https://v.douyin.com/example/",
            resolved_url="https://v5-ali-northeast.douyinvod.com/media/no-extension",
            platform="douyin",
            input_kind="platform_page",
            strategy="douyin_tikhub_direct",
            prefer_subtitles=False,
            title="douyin_123",
            referer="https://v.douyin.com/example/",
        )
        request_transcriber = SimpleNamespace(
            transcribe=AsyncMock(return_value="# Video Transcription\n\nhello"),
        )
        app_main.tasks[task_id] = {
            "status": "processing",
            "progress": 0,
            "message": "created",
            "url": source.input_url,
        }

        try:
            with (
                patch.object(
                    app_main.media_source_resolver,
                    "resolve",
                    new=AsyncMock(return_value=source),
                ),
                patch.object(
                    app_main.video_processor,
                    "fetch_subtitles",
                    new=AsyncMock(),
                ) as subtitle_mock,
                patch.object(
                    app_main.video_processor,
                    "download_and_convert",
                    new=AsyncMock(return_value=("/tmp/nonexistent-front-audio.m4a", "Douyin title")),
                ) as download_mock,
                patch.object(app_main, "_build_request_transcriber", return_value=request_transcriber),
                patch.object(app_main, "_run_post_extract_pipeline", new=AsyncMock()),
                patch.object(app_main, "save_tasks"),
                patch.object(app_main, "broadcast_task_update", new=AsyncMock()),
            ):
                await app_main.process_video_task(
                    task_id,
                    source.input_url,
                    "zh",
                    transcription_provider="elevenlabs",
                )

            subtitle_mock.assert_not_awaited()
            download_mock.assert_awaited_once_with(
                source.resolved_url,
                app_main.TEMP_DIR,
                prefetched_title=source.title,
                referer=source.referer,
            )
            self.assertEqual(app_main.tasks[task_id]["strategy"], "douyin_tikhub_direct")
            self.assertEqual(app_main.tasks[task_id]["resolved_url"], source.resolved_url)
        finally:
            app_main.tasks.pop(task_id, None)
            app_main.active_tasks.pop(task_id, None)


if __name__ == "__main__":
    unittest.main()
