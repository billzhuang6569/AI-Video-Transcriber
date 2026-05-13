<div align="center">

# AI Video Transcriber

English | [中文](README_ZH.md)

An AI-powered tool to transcribe and summarize videos and podcasts — paste a URL from YouTube, TikTok, Bilibili, Apple Podcasts, SoundCloud, and 30+ platforms, **or upload a local file** (audio, video, or plain text).

![Interface](en_video.png)

</div>

## ✨ Features

- 🎥 **Multi-Platform Support**: Works with YouTube, TikTok, Bilibili, Apple Podcasts, SoundCloud, and 30+ more
- 📁 **Local File Upload**: Drag-and-drop or pick a file — supported formats include `.txt` (treated as transcript text), `.mp3`, `.mp4`, `.m4a`, `.wav`, `.webm`, `.mkv`, `.ogg`, `.flac`. Media is normalized with FFmpeg for the configured transcription API; the same optimize → translate → summarize pipeline runs as for URLs
- ⚡ **Subtitle-First Architecture**: For platforms with native subtitles (e.g. YouTube), transcripts are extracted instantly — no audio download needed. The transcription API is only used as a fallback.
- 🗣️ **API-based Transcription**: Speech-to-text uses hosted APIs instead of a local Whisper model. Supported channels: OpenAI-compatible audio transcription, OpenRouter audio transcription, and ElevenLabs Speech to Text (`scribe_v2`).
- 🤖 **AI Text Optimization**: Automatic typo correction, sentence completion, and intelligent paragraphing
- 🌍 **Multi-Language Summaries**: Generate intelligent summaries in multiple languages
- 🔧 **Bring Your Own Model**: Configure any OpenAI-compatible API endpoint (OpenAI, OpenRouter, local LLM, etc.) directly in the UI — enter your API Base URL and API Key, then click **Fetch** to auto-discover all available models and select the one you want
- ⚙️ **Conditional Translation**: Auto-translates the transcript when the summary language differs from the source language
- 📱 **Mobile-Friendly**: Perfect support for mobile devices

[![Star History Chart](https://api.star-history.com/svg?repos=wendy7756/AI-Video-Transcriber&type=Date)](https://star-history.com/#wendy7756/AI-Video-Transcriber&Date)

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- FFmpeg (required for yt-dlp audio extraction and for normalizing uploaded media)
- A transcription API key. The UI supports OpenRouter and ElevenLabs; server-side env vars can also use OpenAI-compatible transcription.

### Installation

#### Method 1: Automatic Installation

```bash
# Clone the repository
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber

# Run installation script
chmod +x install.sh
./install.sh
```

#### Method 2: Docker

```bash
# Clone the repository
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber

# Using Docker Compose (easiest)
cp .env.example .env
# Edit .env file if you want server-side defaults (optional)
docker-compose up -d

# Or using Docker directly
docker build -t ai-video-transcriber .
docker run -p 8000:8000 --env-file .env ai-video-transcriber
```

The image uses **Python 3.12** (Debian Bookworm), upgrades `pip`/`setuptools`/`wheel`, then installs from `requirements.txt` — same version constraints as a fresh local venv on a current Python.

#### Method 3: Manual Installation

1. **Install Python Dependencies**
```bash
# macOS (PEP 668) strongly recommends using a virtualenv
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

2. **Install FFmpeg**
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt update && sudo apt install ffmpeg

# CentOS/RHEL
sudo yum install ffmpeg
```

3. **Configure Environment Variables** *(optional)*
```bash
# If you prefer server-side defaults, set these — otherwise configure via the UI
export TRANSCRIPTION_PROVIDER="openrouter"   # openai / openrouter / elevenlabs
export OPENROUTER_API_KEY="your_transcription_key_here"
export OPENAI_TRANSCRIPTION_MODEL="openai/whisper-large-v3-turbo"

# Summary / translation can use a separate OpenAI-compatible chat endpoint
export OPENAI_API_KEY="your_summary_key_here"
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

### Start the Service

```bash
python3 start.py
```

After the service starts, open your browser and visit `http://localhost:8000`

#### Production Mode (Recommended for long videos)

To avoid SSE disconnections during long processing, start in production mode (hot-reload disabled):

```bash
python3 start.py --prod
```

This keeps the SSE connection stable throughout long tasks (30–60+ min).

#### Run with explicit env (example)

```bash
source venv/bin/activate
export OPENAI_API_KEY=your_api_key_here         # optional: server-side default
export TRANSCRIPTION_PROVIDER=openrouter
export OPENROUTER_API_KEY=your_transcription_key_here
export OPENAI_TRANSCRIPTION_MODEL=openai/whisper-large-v3-turbo
python3 start.py --prod
```

## 📖 Usage Guide

1. **Choose input — URL or file**
   - **Video / podcast URL**: Paste a link from YouTube, Bilibili, or any other supported platform into the input field
   - **Local file**: Drag a file onto the dashed upload area (or click to browse). Same **Transcribe** button starts the job; uploads use the same API route as URLs (`POST /api/process-video` with multipart `file`), which helps when a reverse proxy only allows that path
2. **Select Summary Language**: Choose the output language from the dropdown next to the input area
3. **(Optional) Configure APIs**: Click **AI Settings** to expand the panel
   - Choose the transcription channel: **OpenRouter** or **ElevenLabs**
   - For OpenRouter, choose `openai/whisper-large-v3-turbo`, `openai/whisper-large-v3`, or `google/chirp-3`
   - For ElevenLabs, use `scribe_v2` and enter your ElevenLabs API key
   - Separately configure the summary/translation chat endpoint with **API Base URL**, **API Key**, **Fetch**, and model selection
4. **Start Processing**: Click the **Transcribe** button. For **URL** jobs, the progress bar shows which mode is active:
   - **⚡ Subtitle** (green) — native subtitles found, transcript extracted in seconds
   - **🎙 Transcription API** (amber) — no subtitles available, downloading audio for API transcription
   For **local uploads**, media is normalized with FFmpeg then transcribed through the configured API; plain **`.txt`** files skip download/transcription and go straight into the text pipeline (optimize → summary, and translation when languages differ).
5. **View Results**: Review the optimized transcript and AI summary
   - If transcript language ≠ selected summary language, a **Translation** tab appears automatically
6. **Download Files**: Save Markdown-formatted files (Transcript / Translation / Summary)

## 🛠️ Technical Architecture

### Backend Stack
- **FastAPI**: Modern Python web framework
- **yt-dlp**: Video downloading and processing
- **FFmpeg**: Audio extraction and local upload normalization for API transcription
- **OpenRouter / ElevenLabs / OpenAI-compatible transcription APIs**: Speech transcription
- **OpenAI API**: Text optimization, translation, and summarization

### Frontend Stack
- **HTML5 + CSS3**: Responsive interface design
- **JavaScript (ES6+)**: Modern frontend interactions
- **Marked.js**: Markdown rendering
- **Font Awesome**: Icon library

### Project Structure
```
AI-Video-Transcriber/
├── backend/                 # Backend code
│   ├── main.py             # FastAPI main application
│   ├── video_processor.py  # Video processing module
│   ├── transcriber.py      # Transcription module
│   ├── summarizer.py       # Summary module
│   ├── translator.py       # Translation module
│   └── llm_sanitize.py     # Post-process LLM outputs (strip boilerplate)
├── static/                 # Frontend files
│   ├── index.html          # Main page
│   └── app.js              # Frontend logic
├── temp/                   # Temporary files directory
├── Dockerfile              # Docker image configuration
├── docker-compose.yml      # Docker Compose configuration
├── .dockerignore           # Docker ignore rules
├── .env.example            # Environment variables template
├── requirements.txt        # Python dependencies
├── start.py               # Startup script
└── README.md              # Project documentation
```

## ⚙️ Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `OPENAI_API_KEY` | API key for summary/translation and OpenAI transcription fallback | - | No if configured in UI |
| `TRANSCRIPTION_PROVIDER` | Transcription channel: `openai`, `openrouter`, or `elevenlabs` | `openai` | No |
| `OPENROUTER_API_KEY` | OpenRouter transcription API key | - | Only for OpenRouter server default |
| `OPENAI_TRANSCRIPTION_API_KEY` | OpenAI/OpenRouter transcription API key | falls back to `OPENAI_API_KEY` | No if configured in UI |
| `OPENAI_TRANSCRIPTION_BASE_URL` | OpenAI-compatible transcription base URL | provider default | No |
| `OPENAI_TRANSCRIPTION_MODEL` | OpenAI/OpenRouter transcription model | provider default | No |
| `ELEVENLABS_API_KEY` | ElevenLabs API key for Speech to Text | - | Only for ElevenLabs server default |
| `ELEVENLABS_BASE_URL` | ElevenLabs API base URL | `https://api.elevenlabs.io` | No |
| `ELEVENLABS_TRANSCRIPTION_MODEL` | ElevenLabs speech-to-text model | `scribe_v2` | No |
| `OPENAI_TRANSCRIPTION_MAX_MB` | Safe per-request upload limit for transcription chunks | `24` | No |
| `HOST` | Server address | `0.0.0.0` | No |
| `PORT` | Server port | `8000` | No |
| `UPLOAD_MAX_MB` | Maximum upload size for local files (MB) | `200` | No |

An optional dedicated endpoint `POST /api/process-upload` exists with the same behavior as sending `file` to `/api/process-video`.

For OpenRouter audio transcription, set:

```bash
export TRANSCRIPTION_PROVIDER="openrouter"
export OPENROUTER_API_KEY="your_openrouter_key"
export OPENAI_TRANSCRIPTION_MODEL="openai/whisper-large-v3-turbo"
```

For ElevenLabs Speech to Text, set:

```bash
export TRANSCRIPTION_PROVIDER="elevenlabs"
export ELEVENLABS_API_KEY="your_elevenlabs_key"
export ELEVENLABS_TRANSCRIPTION_MODEL="scribe_v2"
```

### Server API

Use `POST /api/transcribe-url` to submit a media URL. The API returns a `task_id` immediately, then you poll `GET /api/transcribe-url/{task_id}` until the task is completed:

```bash
curl -X POST http://localhost:8000/api/transcribe-url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://www.youtube.com/watch?v=VIDEO_ID",
    "transcription_provider": "openrouter",
    "transcription_model": "openai/whisper-large-v3-turbo",
    "transcription_api_key": "your_transcription_key"
  }'

curl http://localhost:8000/api/transcribe-url/TASK_ID
```

The response shape is stable across providers:

```json
{
  "status": "processing",
  "task_id": "TASK_ID",
  "poll_url": "/api/transcribe-url/TASK_ID",
  "progress": 45,
  "message": "音频准备完成，正在调用转写 API...",
  "data": null,
  "error": null
}
```

When completed:

```json
{
  "status": "completed",
  "task_id": "TASK_ID",
  "poll_url": "/api/transcribe-url/TASK_ID",
  "progress": 100,
  "message": "转写完成",
  "data": {
    "source": {
      "url": "https://www.youtube.com/watch?v=VIDEO_ID",
      "type": "audio",
      "title": "Video title"
    },
    "transcription": {
      "provider": "openrouter",
      "model": "openai/whisper-large-v3-turbo",
      "language": "zh",
      "language_probability": 0.98,
      "text": "Plain transcript text",
      "segments": [
        {"start": 1.0, "end": 9.0, "text": "Segment text"}
      ],
      "markdown": "# Video Transcription..."
    }
  },
  "error": null
}
```

For backward compatibility, completed responses still include the top-level aliases `source_url`, `source_type`, `video_title`, `detected_language`, `transcript`, and `transcript_markdown`.

## 🔧 FAQ

### Q: Why is transcription slow?
A: Transcription speed depends on video length, subtitle availability, download speed, and your selected transcription provider response time.

### Q: Which video platforms are supported?
A: All platforms supported by yt-dlp, including but not limited to: YouTube, TikTok, Facebook, Instagram, Twitter, Bilibili, Youku, iQiyi, Tencent Video, etc.

### Q: What local file types and size limits apply?
A: Allowed extensions include `.txt`, `.mp3`, `.mp4`, `.m4a`, `.wav`, `.webm`, `.mkv`, `.ogg`, `.flac`. Default max size is **200 MB** per file; override with the `UPLOAD_MAX_MB` environment variable on the server.

### Q: What if the AI optimization features are unavailable?
A: AI features require an API key from any OpenAI-compatible provider (OpenAI, OpenRouter, etc.). You can enter it directly in the **AI Settings** panel in the UI — no server restart needed. Alternatively, set `OPENAI_API_KEY` as an environment variable for a server-side default.

### Q: I get HTTP 500 errors when starting/using the service. Why?
A: In most cases this is an environment configuration issue rather than a code bug. Please check:
- Ensure a virtualenv is activated: `source venv/bin/activate`
- Install deps inside the venv: `pip install -r requirements.txt`
- Configure your API keys in the **AI Settings** panel, or set `OPENAI_API_KEY` plus the transcription provider env vars
- Install FFmpeg: `brew install ffmpeg` (macOS) / `sudo apt install ffmpeg` (Debian/Ubuntu)
- If port 8000 is occupied, stop the old process or change `PORT`

### Q: How to handle long videos?
A: The server compresses audio and automatically chunks files above the API upload limit. Very long videos still take longer and may incur higher API usage.

### Q: How to use Docker for deployment?
A: Docker provides the easiest deployment method:

**Prerequisites:**
- Install Docker Desktop from https://www.docker.com/products/docker-desktop/
- Ensure Docker service is running

**Quick Start:**
```bash
# Clone and setup
git clone https://github.com/wendy7756/AI-Video-Transcriber.git
cd AI-Video-Transcriber
cp .env.example .env
# Edit .env file to set server-side defaults (optional)

# Start with Docker Compose (recommended)
docker-compose up -d

# Or build and run manually
docker build -t ai-video-transcriber .
docker run -p 8000:8000 --env-file .env ai-video-transcriber
```

**Common Docker Issues:**
- **Port conflict**: Change port mapping `-p 8001:8000` if 8000 is occupied
- **Permission denied**: Ensure Docker Desktop is running and you have proper permissions
- **Build fails**: Check disk space (need ~2GB free) and network connection
- **Container won't start**: Check Docker logs with `docker logs <container_id>`

**Docker Commands:**
```bash
# View running containers
docker ps

# Check container logs
docker logs ai-video-transcriber-ai-video-transcriber-1

# Stop service
docker-compose down

# Rebuild after changes
docker-compose build --no-cache
```

### Q: What are the memory requirements?
A: Memory usage varies depending on the deployment method and workload:

**Docker / traditional deployment:**
- **Base memory**: roughly 100-200MB while idle
- **During processing**: mostly FFmpeg / yt-dlp working memory; no local Whisper model is loaded
- **Recommended**: 1GB+ RAM for normal API deployment, more for concurrent long-video jobs

### Q: Network connection errors or timeouts?
A: If you encounter network-related errors during video downloading or API calls, try these solutions:

**Common Network Issues:**
- Video download fails with "Unable to extract" or timeout errors
- AI provider API calls return connection timeout or DNS resolution failures
- Docker image pull fails or is extremely slow

**Solutions:**
1. **Switch VPN/Proxy**: Try connecting to a different VPN server or switch your proxy settings
2. **Check Network Stability**: Ensure your internet connection is stable
3. **Retry After Network Change**: Wait 30-60 seconds after changing network settings before retrying
4. **Use Alternative Endpoints**: If using custom AI provider endpoints, verify they're accessible from your network
5. **Docker Network Issues**: Restart Docker Desktop if container networking fails

**Quick Network Test:**
```bash
# Test video platform access
curl -I https://www.youtube.com/

# Test your AI provider endpoint
curl -I https://openrouter.ai

# Test Docker Hub access
docker pull hello-world
```

## 🎯 Supported Languages

### Transcription
- Supports automatic language detection through the configured transcription provider
- Automatic language detection
- High accuracy for major languages

### Summary Generation
- English
- Chinese (Simplified)
- Japanese
- Korean
- Spanish
- French
- German
- Portuguese
- Russian
- Arabic
- And more...

## 📈 Performance Tips

- **Hardware Requirements**:
  - Minimum: 4GB RAM, dual-core CPU
  - Recommended: 8GB RAM, quad-core CPU
  - Ideal: 16GB RAM, multi-core CPU, SSD storage

- **Processing Time Estimates**:

  | Video Length | Subtitle Mode | API Transcription Mode | Notes |
  |-------------|---------------|--------------|-------|
  | 1 minute | ~5s | 30s–1 min | Subtitle mode needs no audio download |
  | 5 minutes | ~10s | 2–5 min | YouTube auto-captions trigger subtitle mode |
  | 15 minutes | ~15s | 5–15 min | Most YouTube videos support subtitle mode |
  | 30+ minutes | ~20s | 15–60 min | Podcast/audio-only always uses the transcription API |

## 🤝 Contributing

We welcome Issues and Pull Requests!

1. Fork the project
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request


## Acknowledgments

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) - Powerful video downloading tool
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [OpenAI](https://openai.com/) - Audio transcription and intelligent text processing API

## 📞 Contact

For questions or suggestions, please submit an Issue or contact Wendy.

---

## 🚀 Try the Full Product — sipsip.ai

This tool is the open-source part of **[sipsip.ai](https://sipsip.ai)**.

The full product goes further:
- 📧 **Daily email briefs** — follow your favorite creators and get an AI-curated digest in your inbox every morning
- ⚡ Transcribe & summarize any video or podcast on demand
- 🌐 Multi-language support across all features

**Free to start** — no credit card required.

➡️ [sipsip.ai](https://sipsip.ai)

---

## ⭐ Star History

If you find this project helpful, please consider giving it a star!
