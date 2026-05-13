import asyncio
import base64
import json
import logging
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    path: Path
    offset_seconds: float
    cleanup: bool = False


class Transcriber:
    """音频转录器，使用外部转写 API 进行语音转文字。"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        max_file_mb: Optional[int] = None,
    ):
        """
        初始化 API 转录器。

        优先级：请求参数 > 服务商专用环境变量 > 通用环境变量 > 服务商默认值。
        """
        self.base_url = (
            (base_url or "").strip().rstrip("/")
            or os.getenv("OPENAI_TRANSCRIPTION_BASE_URL")
            or None
        )
        self.provider = self._resolve_provider(provider)
        self.api_key = self._resolve_api_key(api_key)
        self.model = self._resolve_model(model)
        self.max_file_mb = max_file_mb or int(os.getenv("OPENAI_TRANSCRIPTION_MAX_MB", "24"))
        self.chunk_seconds = int(os.getenv("OPENAI_TRANSCRIPTION_CHUNK_SECONDS", "1200"))
        self.last_detected_language = None
        self.use_openrouter_audio_api = self.provider == "openrouter"
        self.use_elevenlabs_audio_api = self.provider == "elevenlabs"
        self.client = None if (self.use_openrouter_audio_api or self.use_elevenlabs_audio_api) else self._build_client()

    @property
    def is_configured(self) -> bool:
        if self.use_openrouter_audio_api or self.use_elevenlabs_audio_api:
            return bool(self.api_key)
        return self.client is not None

    def _resolve_provider(self, provider: Optional[str]) -> str:
        value = (provider or os.getenv("TRANSCRIPTION_PROVIDER") or "").strip().lower()
        if value in {"openrouter", "elevenlabs", "openai"}:
            return value
        if self.base_url and "openrouter.ai" in self.base_url:
            return "openrouter"
        return "openai"

    def _resolve_api_key(self, api_key: Optional[str]) -> Optional[str]:
        provided = (api_key or "").strip()
        if provided:
            return provided
        if self.provider == "elevenlabs":
            return os.getenv("ELEVENLABS_API_KEY") or os.getenv("OPENAI_TRANSCRIPTION_API_KEY")
        if self.provider == "openrouter":
            return (
                os.getenv("OPENROUTER_API_KEY")
                or os.getenv("OPENAI_TRANSCRIPTION_API_KEY")
                or os.getenv("OPENAI_API_KEY")
            )
        return (
            os.getenv("OPENAI_TRANSCRIPTION_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        )

    def _default_model(self) -> str:
        if self.provider == "openrouter":
            return "openai/whisper-large-v3-turbo"
        if self.provider == "elevenlabs":
            return "scribe_v2"
        return "whisper-1"

    def _resolve_model(self, model: Optional[str]) -> str:
        provided = (model or "").strip()
        if provided:
            return provided

        generic_model = (
            os.getenv("OPENAI_TRANSCRIPTION_MODEL")
            or os.getenv("WHISPER_API_MODEL")
        )
        if self.provider == "elevenlabs":
            elevenlabs_model = os.getenv("ELEVENLABS_TRANSCRIPTION_MODEL")
            if elevenlabs_model:
                return elevenlabs_model
            if generic_model in {"scribe_v2", "scribe_v1"}:
                return generic_model
            return self._default_model()
        if self.provider == "openrouter":
            openrouter_model = os.getenv("OPENROUTER_TRANSCRIPTION_MODEL")
            if openrouter_model:
                return openrouter_model
            if generic_model and generic_model != "whisper-1":
                return generic_model
            return self._default_model()

        return generic_model or self._default_model()

    def _build_client(self) -> Optional[OpenAI]:
        if not self.api_key:
            logger.warning("未设置转写 API Key，音频转写将不可用")
            return None

        kwargs = {"api_key": self.api_key}
        if self.base_url:
            kwargs["base_url"] = self.base_url
            logger.info(f"OpenAI 兼容转写客户端已初始化，base_url={self.base_url}")
        else:
            logger.info("OpenAI 兼容转写客户端已初始化，使用 OpenAI 默认端点")
        return OpenAI(**kwargs)

    async def transcribe(self, audio_path: str, language: Optional[str] = None) -> str:
        """
        转录音频文件。

        Args:
            audio_path: 音频文件路径
            language: 指定语言（可选，如果不指定则自动检测）

        Returns:
            转录文本（Markdown格式）
        """
        try:
            path = Path(audio_path)
            if not path.exists():
                raise Exception(f"音频文件不存在: {audio_path}")
            if not self.is_configured:
                raise Exception("未配置转写 API Key，无法调用转写 API")

            chunks = await self._prepare_audio_chunks(path)
            logger.info(
                f"开始调用转写 API: provider={self.provider}, path={path}, model={self.model}, chunks={len(chunks)}"
            )

            all_segments = []
            fallback_text_parts = []
            detected_language = None
            language_probability = None

            try:
                for index, chunk in enumerate(chunks, start=1):
                    logger.info(f"正在转录音频分片 {index}/{len(chunks)}: {chunk.path}")
                    response = await asyncio.to_thread(
                        self._transcribe_file,
                        chunk.path,
                        language,
                    )

                    detected_language = (
                        detected_language
                        or self._get_value(response, "language")
                        or language
                    )
                    language_probability = (
                        language_probability
                        or self._get_value(response, "language_probability")
                    )
                    segments = self._get_value(response, "segments") or []
                    if segments:
                        all_segments.extend(
                            self._normalize_segments(segments, chunk.offset_seconds)
                        )
                    else:
                        text = self._get_transcript_text(response).strip()
                        if text:
                            fallback_text_parts.append(text)
            finally:
                self._cleanup_chunks(chunks)

            self.last_detected_language = detected_language
            transcript_text = self._format_transcript(
                detected_language=detected_language,
                language_probability=language_probability,
                segments=all_segments,
                fallback_text="\n\n".join(fallback_text_parts),
            )
            logger.info("转写 API 转录完成")
            return transcript_text

        except Exception as e:
            logger.error(f"转录失败: {str(e)}")
            raise Exception(f"转录失败: {str(e)}")

    def _transcribe_file(self, audio_path: Path, language: Optional[str]) -> Any:
        if self.use_openrouter_audio_api:
            return self._transcribe_file_with_openrouter(audio_path, language)
        if self.use_elevenlabs_audio_api:
            return self._transcribe_file_with_elevenlabs(audio_path, language)

        params = {
            "model": self.model,
            "file": audio_path.open("rb"),
        }
        if language:
            params["language"] = language

        # whisper-1 支持 verbose_json 与时间戳；新一代转写模型目前只保证 json/text。
        if self.model == "whisper-1":
            params["response_format"] = "verbose_json"
            params["timestamp_granularities"] = ["segment"]
        else:
            params["response_format"] = "json"

        try:
            return self.client.audio.transcriptions.create(**params)
        finally:
            params["file"].close()

    def _transcribe_file_with_openrouter(self, audio_path: Path, language: Optional[str]) -> Any:
        base_url = self.base_url or "https://openrouter.ai/api/v1"
        api_url = f"{base_url.rstrip('/')}/audio/transcriptions"
        audio_format = self._get_openrouter_audio_format(audio_path)

        with audio_path.open("rb") as f:
            base64_audio = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "model": self.model,
            "input_audio": {
                "data": base64_audio,
                "format": audio_format,
            },
        }
        if language:
            payload["language"] = language

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        referer = os.getenv("OPENROUTER_HTTP_REFERER")
        title = os.getenv("OPENROUTER_APP_TITLE", "AI Video Transcriber")
        if referer:
            headers["HTTP-Referer"] = referer
        if title:
            headers["X-OpenRouter-Title"] = title

        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(api_url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise Exception(f"OpenRouter 转写请求失败: HTTP {e.code} {body[:800]}")
        except urllib.error.URLError as e:
            raise Exception(f"OpenRouter 转写请求失败: {e}")

        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"text": body}

    def _transcribe_file_with_elevenlabs(self, audio_path: Path, language: Optional[str]) -> Any:
        api_url = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io").rstrip("/")
        api_url = f"{api_url}/v1/speech-to-text"
        fields = {
            "model_id": self.model or "scribe_v2",
            "tag_audio_events": "true",
            "timestamps_granularity": "word",
            "diarize": "true",
        }
        if language:
            fields["language_code"] = language

        body, content_type = self._build_multipart_body(fields, audio_path)
        request = urllib.request.Request(
            api_url,
            data=body,
            headers={
                "xi-api-key": self.api_key,
                "Content-Type": content_type,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=900) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            response_body = e.read().decode("utf-8", errors="replace")
            raise Exception(f"ElevenLabs 转写请求失败: HTTP {e.code} {response_body[:800]}")
        except urllib.error.URLError as e:
            raise Exception(f"ElevenLabs 转写请求失败: {e}")

        try:
            return self._normalize_elevenlabs_response(json.loads(response_body))
        except json.JSONDecodeError:
            return {"text": response_body}

    def _build_multipart_body(self, fields: dict, audio_path: Path) -> tuple[bytes, str]:
        boundary = f"----sipsip{uuid.uuid4().hex}"
        chunks = []

        for name, value in fields.items():
            chunks.extend([
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ])

        filename = audio_path.name
        content_type = self._guess_audio_content_type(audio_path)
        chunks.extend([
            f"--{boundary}\r\n".encode("utf-8"),
            (
                f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
                f"Content-Type: {content_type}\r\n\r\n"
            ).encode("utf-8"),
            audio_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode("utf-8"),
        ])

        return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

    def _guess_audio_content_type(self, audio_path: Path) -> str:
        suffix = audio_path.suffix.lower()
        return {
            ".m4a": "audio/mp4",
            ".mp4": "video/mp4",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".webm": "audio/webm",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
        }.get(suffix, "application/octet-stream")

    def _normalize_elevenlabs_response(self, payload: Any) -> dict:
        if not isinstance(payload, dict):
            return {"text": str(payload)}

        if isinstance(payload.get("transcripts"), list):
            transcripts = [self._normalize_elevenlabs_response(t) for t in payload["transcripts"]]
            text = "\n\n".join(t.get("text", "") for t in transcripts if t.get("text"))
            segments = []
            language = None
            language_probability = None
            for transcript in transcripts:
                language = language or transcript.get("language")
                language_probability = language_probability or transcript.get("language_probability")
                segments.extend(transcript.get("segments") or [])
            return {
                "text": text,
                "language": language,
                "language_probability": language_probability,
                "segments": segments,
            }

        language = self._normalize_language_code(payload.get("language_code"))
        words = payload.get("words") or []
        return {
            "text": payload.get("text") or "",
            "language": language,
            "language_probability": payload.get("language_probability"),
            "segments": self._segments_from_words(words),
        }

    def _normalize_language_code(self, code: Optional[str]) -> Optional[str]:
        if not code:
            return None
        value = str(code).strip().lower()
        iso3_map = {
            "eng": "en",
            "zho": "zh",
            "cmn": "zh",
            "yue": "zh",
            "jpn": "ja",
            "kor": "ko",
            "spa": "es",
            "fra": "fr",
            "fre": "fr",
            "deu": "de",
            "ger": "de",
            "ita": "it",
            "por": "pt",
            "rus": "ru",
            "ara": "ar",
        }
        return iso3_map.get(value, value[:2] if len(value) > 2 else value)

    def _segments_from_words(self, words: list) -> List[dict]:
        segments = []
        current_text = ""
        current_start = None
        current_end = None
        current_speaker = None

        for word in words:
            if not isinstance(word, dict):
                continue
            text = word.get("text") or ""
            kind = word.get("type")
            start = word.get("start")
            end = word.get("end")
            speaker = word.get("speaker_id")

            if kind == "spacing":
                current_text += text
                continue
            if not text:
                continue

            should_flush = False
            if current_text and speaker and current_speaker and speaker != current_speaker:
                should_flush = True
            if current_text and current_start is not None and start is not None and float(start) - float(current_start) >= 12:
                should_flush = True

            if should_flush:
                self._append_word_segment(segments, current_text, current_start, current_end)
                current_text = ""
                current_start = None
                current_end = None

            if current_start is None and start is not None:
                current_start = float(start)
            if end is not None:
                current_end = float(end)
            if speaker:
                current_speaker = speaker

            current_text += text
            if text.rstrip().endswith((".", "!", "?", "。", "！", "？", "\n")):
                self._append_word_segment(segments, current_text, current_start, current_end)
                current_text = ""
                current_start = None
                current_end = None

        if current_text.strip():
            self._append_word_segment(segments, current_text, current_start, current_end)

        return segments

    def _append_word_segment(
        self,
        segments: List[dict],
        text: str,
        start: Optional[float],
        end: Optional[float],
    ) -> None:
        clean = text.strip()
        if not clean:
            return
        segments.append({
            "start": float(start or 0),
            "end": float(end or start or 0),
            "text": clean,
        })

    def _get_openrouter_audio_format(self, audio_path: Path) -> str:
        suffix = audio_path.suffix.lower().lstrip(".")
        if suffix == "m4a":
            return "m4a"
        if suffix in {"mp3", "mp4", "mpeg", "mpga", "wav", "webm"}:
            return suffix
        return "wav"

    async def _prepare_audio_chunks(self, audio_path: Path) -> List[AudioChunk]:
        max_bytes = self.max_file_mb * 1024 * 1024
        if audio_path.stat().st_size <= max_bytes:
            return [AudioChunk(path=audio_path, offset_seconds=0.0, cleanup=False)]

        duration = await asyncio.to_thread(self._probe_duration, audio_path)
        if duration <= 0:
            raise Exception(
                f"音频文件超过 {self.max_file_mb}MB，且无法读取时长进行分片"
            )

        chunk_dir = audio_path.parent / f"transcribe_chunks_{uuid.uuid4().hex[:8]}"
        chunk_dir.mkdir(parents=True, exist_ok=True)

        chunks: List[AudioChunk] = []
        start = 0.0
        while start < duration - 0.1:
            current_duration = min(float(self.chunk_seconds), duration - start)
            chunk_path = chunk_dir / f"chunk_{len(chunks) + 1:03d}.m4a"

            while True:
                await asyncio.to_thread(
                    self._export_chunk,
                    audio_path,
                    chunk_path,
                    start,
                    current_duration,
                )
                if chunk_path.stat().st_size <= max_bytes:
                    break
                if current_duration <= 30:
                    raise Exception(
                        f"音频分片仍超过 {self.max_file_mb}MB，请降低 OPENAI_TRANSCRIPTION_CHUNK_SECONDS"
                    )
                chunk_path.unlink(missing_ok=True)
                current_duration = max(30.0, current_duration / 2)

            chunks.append(AudioChunk(path=chunk_path, offset_seconds=start, cleanup=True))
            start += current_duration

        logger.info(f"音频已按 API 上传限制切分为 {len(chunks)} 个分片")
        return chunks

    def _probe_duration(self, audio_path: Path) -> float:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"ffprobe 读取时长失败: {(result.stderr or result.stdout).strip()}")
            return 0.0
        try:
            return float((result.stdout or "0").strip())
        except ValueError:
            return 0.0

    def _export_chunk(
        self,
        source_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
    ) -> None:
        cmd = [
            "ffmpeg",
            "-y",
            "-nostdin",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(source_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "64k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not output_path.exists():
            err = (result.stderr or result.stdout or "").strip()
            raise Exception(f"FFmpeg 音频分片失败: {err[:800]}")

    def _cleanup_chunks(self, chunks: List[AudioChunk]) -> None:
        cleanup_dirs = set()
        for chunk in chunks:
            if chunk.cleanup:
                cleanup_dirs.add(chunk.path.parent)
        for cleanup_dir in cleanup_dirs:
            try:
                shutil.rmtree(cleanup_dir)
            except Exception as e:
                logger.warning(f"清理转录分片失败: {cleanup_dir}, {e}")

    def _normalize_segments(self, segments: Any, offset_seconds: float) -> List[dict]:
        normalized = []
        for segment in segments:
            text = (self._get_value(segment, "text") or "").strip()
            if not text:
                continue
            start = float(self._get_value(segment, "start") or 0) + offset_seconds
            end = float(self._get_value(segment, "end") or start) + offset_seconds
            normalized.append({"start": start, "end": end, "text": text})
        return normalized

    def _format_transcript(
        self,
        detected_language: Optional[str],
        language_probability: Optional[float],
        segments: List[dict],
        fallback_text: str,
    ) -> str:
        probability = "—"
        if isinstance(language_probability, (int, float)):
            probability = f"{language_probability:.2f}"
        lines = [
            "# Video Transcription",
            "",
            f"**Detected Language:** {detected_language or ''}",
            f"**Language Probability:** {probability}",
            "",
            "## Transcription Content",
            "",
        ]

        if segments:
            for segment in segments:
                start_time = self._format_time(segment["start"])
                end_time = self._format_time(segment["end"])
                lines.append(f"**[{start_time} - {end_time}]**")
                lines.append("")
                lines.append(segment["text"])
                lines.append("")
        elif fallback_text:
            lines.append(fallback_text)
            lines.append("")

        return "\n".join(lines)

    def _get_transcript_text(self, response: Any) -> str:
        if isinstance(response, str):
            return response
        return self._get_value(response, "text") or ""

    def _get_value(self, obj: Any, name: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    def _format_time(self, seconds: float) -> str:
        """
        将秒数转换为时分秒格式。
        """
        total_seconds = max(0, int(seconds))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def get_supported_languages(self) -> list:
        """
        获取常用支持语言列表；不同转写服务商支持范围可能不同。
        """
        return [
            "zh", "en", "ja", "ko", "es", "fr", "de", "it", "pt", "ru",
            "ar", "hi", "th", "vi", "tr", "pl", "nl", "sv", "da", "no"
        ]

    def get_detected_language(self, transcript_text: Optional[str] = None) -> Optional[str]:
        """
        获取检测到的语言。
        """
        if transcript_text and "**Detected Language:**" in transcript_text:
            lines = transcript_text.split("\n")
            for line in lines:
                if "**Detected Language:**" in line:
                    lang = (
                        line.split("**Detected Language:**", 1)[-1]
                        .strip()
                        .strip("*")
                        .strip()
                    )
                    return lang if lang else None

        if self.last_detected_language:
            return self.last_detected_language

        return None
