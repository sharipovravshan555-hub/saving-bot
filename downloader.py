import asyncio
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import imageio_ffmpeg
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


class AuthenticationRequiredError(RuntimeError):
    pass


class MediaUnavailableError(RuntimeError):
    pass


class MediaTooLargeError(RuntimeError):
    pass


class DownloadTimeoutError(RuntimeError):
    pass


@dataclass(frozen=True)
class RemoteMedia:
    url: str
    filesize: int | None = None


class Downloader:
    def __init__(
        self,
        tmp_root: Path,
        max_concurrent: int,
        cookies_file: Path | None = None,
        pot_server_home: Path | None = None,
        node_executable: str | None = None,
        timeout: int = 900,
        upload_limit_mb: int = 50,
    ):
        self.tmp_root = tmp_root
        self.cookies_file = cookies_file
        self.pot_server_home = pot_server_home
        self.node_executable = node_executable
        self.timeout = max(30, timeout)
        self.upload_limit = max(1, upload_limit_mb) * 1024 * 1024
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def download(self, url: str, mode: str, quality: str | None = None) -> Path:
        async with self.semaphore:
            return await asyncio.to_thread(self._download_sync, url, mode, quality)

    async def resolve_remote_video(
        self, url: str, quality: str | None = None
    ) -> RemoteMedia:
        async with self.semaphore:
            return await asyncio.to_thread(self._resolve_remote_video_sync, url, quality)

    def _resolve_remote_video_sync(
        self, url: str, quality: str | None = None
    ) -> RemoteMedia:
        self.validate_url(url)
        height = quality or "720"
        ydl_opts = {
            "format": (
                f"b[height<={height}][ext=mp4]/"
                f"b[height<={height}]/best[ext=mp4]/best"
            ),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
            **self._runtime_options(),
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        downloads = info.get("requested_downloads") or [info]
        remote_url = downloads[0].get("url")
        if not remote_url or not remote_url.startswith("https://"):
            raise RuntimeError("A public HTTPS media URL was not found")
        filesize = downloads[0].get("filesize") or downloads[0].get("filesize_approx")
        return RemoteMedia(remote_url, int(filesize) if filesize else None)

    def _download_sync(self, url: str, mode: str, quality: str | None) -> Path:
        self.validate_url(url)
        job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=self.tmp_root))
        outtmpl = str(job_dir / "%(title).180s.%(ext)s")
        started_at = time.monotonic()

        def progress_hook(_: dict) -> None:
            if time.monotonic() - started_at > self.timeout:
                raise DownloadTimeoutError("Download deadline exceeded")

        common_opts = {
            "concurrent_fragment_downloads": 8,
            "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
            "fragment_retries": 3,
            "noplaylist": True,
            "quiet": True,
            "retries": 3,
            "socket_timeout": 20,
            "no_warnings": True,
            "noprogress": True,
            "windowsfilenames": True,
            "max_filesize": self.upload_limit,
            "progress_hooks": [progress_hook],
            **self._runtime_options(),
        }
        if self.cookies_file and self.cookies_file.is_file():
            common_opts["cookiefile"] = str(self.cookies_file)
        if mode == "audio":
            ydl_opts = {
                **common_opts,
                "format": "bestaudio/best",
                "outtmpl": outtmpl,
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        else:
            height = quality or "720"
            video_format = (
                f"bv*[height<={height}][ext=mp4]+ba[ext=m4a]/"
                f"b[height<={height}][ext=mp4]/best[height<={height}]/best"
            )
            ydl_opts = {
                **common_opts,
                "format": video_format,
                "outtmpl": outtmpl,
                "merge_output_format": "mp4",
            }

        clients = (None, "mweb") if self._is_youtube_url(url) else (None,)
        last_error = None

        for client in clients:
            attempt_opts = dict(ydl_opts)
            if client:
                extractor_args = {
                    "youtube": {
                        "player_client": [client],
                        "fetch_pot": ["always"],
                    }
                }
                if self.pot_server_home:
                    extractor_args["youtubepot-bgutilscript"] = {
                        "server_home": [str(self.pot_server_home)]
                    }
                attempt_opts["extractor_args"] = extractor_args

            try:
                with YoutubeDL(attempt_opts) as ydl:
                    ydl.extract_info(url, download=True)

                files = [file for file in job_dir.iterdir() if file.is_file()]
                if not files:
                    raise MediaTooLargeError("No media fits the upload limit")
                result = max(files, key=lambda file: file.stat().st_size)
                if result.stat().st_size > self.upload_limit:
                    raise MediaTooLargeError("Downloaded media exceeds upload limit")
                return result
            except (DownloadTimeoutError, MediaTooLargeError):
                shutil.rmtree(job_dir, ignore_errors=True)
                raise
            except DownloadError as error:
                last_error = error
                if client != clients[-1]:
                    shutil.rmtree(job_dir, ignore_errors=True)
                    job_dir.mkdir()
                    continue
                break
            except Exception:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise

        shutil.rmtree(job_dir, ignore_errors=True)
        message = str(last_error).lower()
        if any(
            marker in message
            for marker in (
                "video unavailable",
                "private video",
                "not available in your country",
                "this content isn't available",
                "removed by the uploader",
            )
        ):
            raise MediaUnavailableError("Media is unavailable") from last_error
        if any(
            marker in message
            for marker in (
                "sign in to confirm",
                "confirm you're not a bot",
                "confirm you’re not a bot",
                "authentication",
                "cookies",
            )
        ):
            raise AuthenticationRequiredError("YouTube authentication is required") from last_error
        if "download deadline exceeded" in message:
            raise DownloadTimeoutError("Download deadline exceeded") from last_error
        raise last_error

    def _runtime_options(self) -> dict:
        if not self.node_executable:
            return {}
        return {"js_runtimes": {"node": {"path": self.node_executable}}}

    @staticmethod
    def validate_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            raise ValueError("Unsupported URL")
        host = (parsed.hostname or "").lower().rstrip(".")
        allowed = (
            host == "youtu.be"
            or host == "youtube.com"
            or host.endswith(".youtube.com")
            or host == "instagram.com"
            or host.endswith(".instagram.com")
            or host == "tiktok.com"
            or host.endswith(".tiktok.com")
        )
        if not allowed:
            raise ValueError("Unsupported media host")
        return url

    @staticmethod
    def _is_youtube_url(url: str) -> bool:
        host = urlparse(url).hostname or ""
        return host == "youtu.be" or host.endswith("youtube.com")

    @staticmethod
    def supports_remote_video(url: str) -> bool:
        host = urlparse(url).hostname or ""
        return (
            host == "instagram.com"
            or host.endswith(".instagram.com")
            or host == "tiktok.com"
            or host.endswith(".tiktok.com")
        )

    @classmethod
    def supports_direct_fetch(cls, url: str) -> bool:
        try:
            cls.validate_url(url)
        except ValueError:
            return False
        return True

    @staticmethod
    def canonical_url(url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host == "instagram.com" or host.endswith(".instagram.com"):
            path = parsed.path.rstrip("/") + "/"
            return urlunparse(("https", host, path, "", "", ""))
        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            return urlunparse(("https", host, parsed.path, "", "", ""))
        if host == "youtu.be":
            return urlunparse(("https", host, parsed.path, "", "", ""))
        if host.endswith("youtube.com"):
            video_id = parse_qs(parsed.query).get("v", [""])[0]
            if video_id:
                return urlunparse(
                    ("https", "www.youtube.com", "/watch", "", urlencode({"v": video_id}), "")
                )
        return url

    @staticmethod
    def cleanup(file_path: Path) -> None:
        shutil.rmtree(file_path.parent, ignore_errors=True)
