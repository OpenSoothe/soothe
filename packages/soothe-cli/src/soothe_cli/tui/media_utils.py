"""Utilities for handling image and video media from clipboard and files."""

from __future__ import annotations

import base64
import io
import logging
import pathlib
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_CLIPBOARD_SUBPROCESS_TIMEOUT_SECONDS = 5
"""Timeout for OS clipboard helper subprocesses."""

_CLIPBOARD_IMAGE_MIME_TYPES: tuple[str, ...] = (
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/gif",
    "image/bmp",
)
"""MIME types probed when reading images from Linux clipboards."""

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
        ".ico",
    }
)
"""Common image file extensions supported by PIL."""

VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".mp4",
        ".mov",
        ".avi",
        ".webm",
        ".m4v",
        ".wmv",
    }
)
"""Video file extensions with validated magic-byte support."""

MAX_MEDIA_BYTES: int = 20 * 1024 * 1024
"""Maximum media file size (20 MB). Keeps base64 payload under ~27 MB."""


def _import_pil() -> tuple[type, type] | None:
    """Import Pillow types when available.

    Returns:
        `(Image, UnidentifiedImageError)` when Pillow is installed, else `None`.
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ModuleNotFoundError:
        logger.debug("Pillow is not installed; image clipboard/path handling is disabled")
        return None
    return Image, UnidentifiedImageError


@dataclass
class ImageData:
    """Represents a pasted image with its base64 encoding."""

    base64_data: str
    format: str  # "png", "jpeg", etc.
    placeholder: str  # Display text like "[image 1]"


@dataclass
class VideoData:
    """Represents a pasted video with its base64 encoding."""

    base64_data: str
    format: str  # "mp4", "quicktime", etc.
    placeholder: str  # Display text like "[video 1]"


def image_data_from_bytes(
    image_bytes: bytes,
    *,
    fallback_format: str | None = None,
) -> ImageData | None:
    """Validate raw image bytes and wrap them as `ImageData`.

    Args:
        image_bytes: Encoded image payload (PNG/JPEG/…).
        fallback_format: Format hint when Pillow cannot detect one.

    Returns:
        `ImageData` when bytes are a valid image under size limits, else `None`.
    """
    if not image_bytes:
        return None
    if len(image_bytes) > MAX_MEDIA_BYTES:
        logger.warning(
            "Clipboard/path image is too large (%d MB, max %d MB)",
            len(image_bytes) // (1024 * 1024),
            MAX_MEDIA_BYTES // (1024 * 1024),
        )
        return None

    pil = _import_pil()
    if pil is None:
        return None
    Image, UnidentifiedImageError = pil  # noqa: N806

    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = (image.format or "").lower()
    except (UnidentifiedImageError, OSError) as e:
        logger.debug("Failed to decode image bytes: %s", e, exc_info=True)
        return None

    if image_format == "jpg":
        image_format = "jpeg"
    if not image_format:
        hint = (fallback_format or "png").lower().removeprefix(".")
        image_format = "jpeg" if hint == "jpg" else hint
    if not image_format:
        image_format = "png"

    return ImageData(
        base64_data=encode_to_base64(image_bytes),
        format=image_format,
        placeholder="[image]",
    )


def get_image_from_path(path: pathlib.Path) -> ImageData | None:
    """Read and encode an image file from disk.

    Args:
        path: Path to the image file.

    Returns:
        `ImageData` when the file is a valid image, otherwise `None`.
    """
    suffix = path.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        return None

    try:
        file_size = path.stat().st_size
        if file_size == 0:
            logger.debug("Image file is empty: %s", path)
            return None
        if file_size > MAX_MEDIA_BYTES:
            logger.warning(
                "Image file %s is too large (%d MB, max %d MB)",
                path,
                file_size // (1024 * 1024),
                MAX_MEDIA_BYTES // (1024 * 1024),
            )
            return None

        image_bytes = path.read_bytes()
    except OSError as e:
        logger.debug("Failed to load image from %s: %s", path, e, exc_info=True)
        return None

    return image_data_from_bytes(
        image_bytes,
        fallback_format=suffix.removeprefix("."),
    )


def get_image_from_clipboard() -> ImageData | None:
    """Read an image from the OS clipboard when present.

    Terminal paste events cannot carry binary image data. This helper reads
    the local OS clipboard via Pillow and/or platform tools.

    Returns:
        `ImageData` when the clipboard holds a usable image, else `None`.
    """
    raw = _read_clipboard_image_bytes()
    if not raw:
        return None
    return image_data_from_bytes(raw, fallback_format="png")


def _read_clipboard_image_bytes() -> bytes | None:
    """Return raw image bytes from the OS clipboard, if any.

    Returns:
        Encoded image bytes, or `None` when no image is available.
    """
    readers = (
        _read_clipboard_image_pillow,
        _read_clipboard_image_macos,
        _read_clipboard_image_wsl,
        _read_clipboard_image_wayland,
        _read_clipboard_image_x11,
    )
    for reader in readers:
        try:
            data = reader()
        except Exception:  # noqa: BLE001  # Clipboard helpers must never crash paste
            logger.debug("Clipboard image reader %s failed", reader.__name__, exc_info=True)
            continue
        if data:
            return data
    return None


def _read_clipboard_image_pillow() -> bytes | None:
    """Try Pillow `ImageGrab.grabclipboard()` when available.

    Returns:
        PNG-encoded bytes, a path-backed image payload, or `None`.
    """
    if _import_pil() is None:
        return None
    try:
        from PIL import ImageGrab
    except ModuleNotFoundError:
        return None

    try:
        grabbed = ImageGrab.grabclipboard()
    except Exception:  # noqa: BLE001  # Platform ImageGrab support varies
        logger.debug("Pillow ImageGrab.grabclipboard failed", exc_info=True)
        return None

    if grabbed is None:
        return None

    # Some platforms return a list of file paths copied to the clipboard.
    if isinstance(grabbed, (list, tuple)):
        for item in grabbed:
            path = pathlib.Path(str(item))
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                try:
                    return path.read_bytes()
                except OSError:
                    continue
        return None

    if not hasattr(grabbed, "save"):
        return None

    buf = io.BytesIO()
    try:
        grabbed.save(buf, format="PNG")
    except OSError:
        logger.debug("Failed to encode clipboard ImageGrab result as PNG", exc_info=True)
        return None
    return buf.getvalue() or None


def _read_clipboard_image_macos() -> bytes | None:
    """Read clipboard image bytes on macOS via pngpaste or osascript.

    Returns:
        Image bytes when available on Darwin, else `None`.
    """
    if sys.platform != "darwin":
        return None

    if shutil.which("pngpaste"):
        proc = _run_clipboard_command(["pngpaste", "-"])
        if proc is not None and proc.returncode == 0 and proc.stdout:
            return proc.stdout

    # AppleScript: write clipboard PNG class to a temp file and read it back.
    with tempfile.TemporaryDirectory(prefix="soothe-clip-") as tmp:
        out_path = pathlib.Path(tmp) / "clipboard.png"
        script = (
            "try\n"
            "  set pngData to the clipboard as «class PNGf»\n"
            "on error\n"
            '  return ""\n'
            "end try\n"
            f'set outPath to "{out_path}"\n'
            "set f to open for access (POSIX file outPath) with write permission\n"
            "set eof of f to 0\n"
            "write pngData to f\n"
            "close access f\n"
            "return outPath\n"
        )
        proc = _run_clipboard_command(["osascript", "-e", script])
        if proc is None or proc.returncode != 0:
            return None
        if not out_path.is_file():
            return None
        data = out_path.read_bytes()
        return data or None


def _read_clipboard_image_wayland() -> bytes | None:
    """Read clipboard image bytes via `wl-paste` when available.

    Returns:
        Image bytes when available, else `None`.
    """
    if not shutil.which("wl-paste"):
        return None

    for mime in _CLIPBOARD_IMAGE_MIME_TYPES:
        proc = _run_clipboard_command(["wl-paste", "--type", mime, "--no-newline"])
        if proc is not None and proc.returncode == 0 and proc.stdout:
            return proc.stdout
    return None


def _read_clipboard_image_x11() -> bytes | None:
    """Read clipboard image bytes on X11 via `xclip`.

    Returns:
        Image bytes when available, else `None`.
    """
    if not shutil.which("xclip"):
        return None

    targets_proc = _run_clipboard_command(
        ["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"]
    )
    targets_text = ""
    if targets_proc is not None and targets_proc.returncode == 0 and targets_proc.stdout:
        targets_text = targets_proc.stdout.decode("utf-8", errors="ignore")

    mime_candidates = [
        mime for mime in _CLIPBOARD_IMAGE_MIME_TYPES if mime in targets_text
    ] or list(_CLIPBOARD_IMAGE_MIME_TYPES)

    for mime in mime_candidates:
        proc = _run_clipboard_command(["xclip", "-selection", "clipboard", "-t", mime, "-o"])
        if proc is not None and proc.returncode == 0 and proc.stdout:
            return proc.stdout
    return None


def _read_clipboard_image_wsl() -> bytes | None:
    """Read Windows clipboard image bytes from WSL via PowerShell.

    Returns:
        PNG bytes when WSL interop succeeds, else `None`.
    """
    if not _is_wsl():
        return None
    if not shutil.which("powershell.exe"):
        return None

    # Emit base64 PNG on stdout when the Windows clipboard contains an image.
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "if (-not [System.Windows.Forms.Clipboard]::ContainsImage()) { exit 2 }; "
        "$img = [System.Windows.Forms.Clipboard]::GetImage(); "
        "$ms = New-Object System.IO.MemoryStream; "
        "$img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); "
        "[Convert]::ToBase64String($ms.ToArray())"
    )
    proc = _run_clipboard_command(["powershell.exe", "-NoProfile", "-Command", ps_script])
    if proc is None or proc.returncode != 0 or not proc.stdout:
        return None
    try:
        return base64.b64decode(proc.stdout.strip())
    except (ValueError, TypeError):
        logger.debug("Failed to decode WSL clipboard PNG base64", exc_info=True)
        return None


def _is_wsl() -> bool:
    """Return whether the current Linux host appears to be WSL.

    Returns:
        `True` when `/proc/version` mentions Microsoft/WSL.
    """
    if sys.platform != "linux":
        return False
    try:
        version = pathlib.Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def _run_clipboard_command(cmd: list[str]) -> subprocess.CompletedProcess[bytes] | None:
    """Run a clipboard helper command with a short timeout.

    Args:
        cmd: Argument vector to execute.

    Returns:
        Completed process, or `None` on timeout / OS error.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            timeout=_CLIPBOARD_SUBPROCESS_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.debug("Clipboard command %s failed: %s", cmd[:1], e)
        return None


def _detect_video_format(data: bytes) -> str | None:
    """Detect video MIME subtype from magic bytes.

    Args:
        data: Raw file bytes (at least 12 bytes for reliable detection).

    Returns:
        MIME subtype (e.g. "mp4", "webm") or `None` if unrecognized.
    """
    min_avi_len = 12
    if data[4:8] == b"ftyp":
        # ftyp box: major brand at bytes 8-12 distinguishes MOV vs MP4
        brand = data[8:12]
        if brand == b"qt  ":
            return "quicktime"
        return "mp4"
    if data[:4] == b"RIFF" and len(data) >= min_avi_len and data[8:12] == b"AVI ":
        return "avi"
    if data[:4] == b"\x30\x26\xb2\x75":  # ASF/WMV
        return "x-ms-wmv"
    if data[:4] == b"\x1a\x45\xdf\xa3":  # WebM/Matroska (EBML header)
        return "webm"
    return None


def get_video_from_path(path: pathlib.Path) -> VideoData | None:
    """Read and encode a video file from disk.

    Args:
        path: Path to the video file.

    Returns:
        `VideoData` when the file is a valid video, otherwise `None`.
    """
    suffix = path.suffix.lower()
    if suffix not in VIDEO_EXTENSIONS:
        return None

    try:
        file_size = path.stat().st_size
        if file_size == 0:
            logger.debug("Video file is empty: %s", path)
            return None
        if file_size > MAX_MEDIA_BYTES:
            logger.warning(
                "Video file %s is too large (%d MB, max %d MB)",
                path,
                file_size // (1024 * 1024),
                MAX_MEDIA_BYTES // (1024 * 1024),
            )
            return None

        video_bytes = path.read_bytes()

        # Validate it's a real video file by checking magic bytes
        # MP4 starts with ftyp, MOV also uses ftyp, AVI starts with RIFF
        min_video_len = 8
        if len(video_bytes) < min_video_len:
            logger.debug("Video file too small (%d bytes): %s", len(video_bytes), path)
            return None

        # Detect format from magic bytes (not extension) so renamed files
        # get the correct MIME type.
        detected_format = _detect_video_format(video_bytes)
        if detected_format is None:
            logger.warning(
                "Video file %s has unrecognized signature for extension '%s'; "
                "skipping. If this is a valid video, the format may not be "
                "supported yet.",
                path,
                suffix,
            )
            return None

        return VideoData(
            base64_data=encode_to_base64(video_bytes),
            format=detected_format,
            placeholder="[video]",
        )
    except OSError as e:
        logger.warning("Failed to load video from %s: %s", path, e, exc_info=True)
        return None


def get_media_from_path(path: pathlib.Path) -> ImageData | VideoData | None:
    """Try to load a file as an image first, then as a video.

    Args:
        path: Path to the media file.

    Returns:
        `ImageData` or `VideoData` if the file is valid media, otherwise `None`.
    """
    result: ImageData | VideoData | None = get_image_from_path(path)
    if result is not None:
        return result
    return get_video_from_path(path)


def encode_to_base64(data: bytes) -> str:
    """Encode raw bytes to a base64 string.

    Args:
        data: Raw bytes to encode.

    Returns:
        Base64-encoded string.
    """
    return base64.b64encode(data).decode("utf-8")
