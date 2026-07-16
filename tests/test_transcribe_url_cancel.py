import asyncio
import json
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch


BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

import main as app_main  # noqa: E402


def response_payload(response):
    if isinstance(response, dict):
        return response
    return json.loads(response.body)


class CancelTranscribeUrlTaskTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancels_running_task_and_keeps_terminal_status(self):
        task_id = str(uuid.uuid4())

        async def wait_forever():
            await asyncio.Event().wait()

        worker = asyncio.create_task(wait_forever())
        await asyncio.sleep(0)
        app_main.tasks[task_id] = {
            "kind": "transcribe_url",
            "status": "processing",
            "progress": 45,
            "message": "working",
            "source_url": "https://example.com/video.mp4",
        }
        app_main.active_tasks[task_id] = worker

        try:
            with (
                patch.object(app_main, "save_tasks") as save_mock,
                patch.object(app_main, "broadcast_task_update", new=AsyncMock()) as broadcast_mock,
            ):
                response = await app_main.cancel_transcribe_url_task(task_id)

            payload = response_payload(response)
            self.assertEqual(payload["status"], "cancelled")
            self.assertEqual(payload["progress"], 100)
            self.assertEqual(payload["task_id"], task_id)
            self.assertIsNone(payload["data"])
            self.assertIsNone(payload["error"])
            self.assertTrue(worker.cancelled())
            self.assertNotIn(task_id, app_main.active_tasks)
            save_mock.assert_called_once()
            broadcast_mock.assert_awaited_once()
        finally:
            app_main.tasks.pop(task_id, None)
            app_main.active_tasks.pop(task_id, None)
            if not worker.done():
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)

    async def test_repeated_cancel_is_idempotent(self):
        task_id = str(uuid.uuid4())
        app_main.tasks[task_id] = {
            "kind": "transcribe_url",
            "status": "cancelled",
            "progress": 100,
            "message": "任务已取消",
            "source_url": "https://example.com/video.mp4",
        }
        try:
            response = await app_main.cancel_transcribe_url_task(task_id)
            payload = response_payload(response)
            self.assertEqual(payload["status"], "cancelled")
            self.assertEqual(payload["cancel_url"], f"/api/transcribe-url/{task_id}/cancel")
        finally:
            app_main.tasks.pop(task_id, None)

    async def test_completed_task_returns_conflict(self):
        task_id = str(uuid.uuid4())
        app_main.tasks[task_id] = {
            "kind": "transcribe_url",
            "status": "completed",
            "progress": 100,
            "message": "转写完成",
            "source_url": "https://example.com/video.mp4",
            "transcript_markdown": "",
        }
        try:
            response = await app_main.cancel_transcribe_url_task(task_id)
            payload = response_payload(response)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(payload["status"], "completed")
            self.assertEqual(payload["error"]["code"], "task_not_cancellable")
        finally:
            app_main.tasks.pop(task_id, None)


if __name__ == "__main__":
    unittest.main()
