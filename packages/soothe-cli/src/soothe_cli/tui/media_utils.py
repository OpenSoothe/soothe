"""Utilities for handling image and video media from clipboard and files."""

import base64
import io
import logging
import pathlib
from dataclasses import dataclass

logger = logging.getLogger(__name__)

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

    def to_message_content(self) -> dict:
        """Convert to LangChain message content format.

        Returns:
            Dict with type and image_url for multimodal messages.
        """
        return {
            "type": "image_url",
            "image_url": {"url": f"data:image/{self.format};base64,{self.base64_data}"},
        }


@dataclass
class VideoData:
    """Represents a pasted video with its base64 encoding."""

    base64_data: str
    format: str  # "mp4", "quicktime", etc.
    placeholder: str  # Display text like "[video 1]"

    def to_message_content(self) -> dict:
        """Convert to LangChain `VideoContentBlock` format.

        Returns:
            `VideoContentBlock` with base64 data and mime_type.
        """
        from langchain_core.messages.content import create_video_block

        return create_video_block(
            base64=self.base64_data,
            mime_type=f"video/{self.format}",
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

    pil = _import_pil()
    if pil is None:
        return None
    Image, UnidentifiedImageError = pil  # noqa: N806

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
        if not image_bytes:
            return None

        with Image.open(io.BytesIO(image_bytes)) as image:
            image_format = (image.format or "").lower()

        if image_format == "jpg":
            image_format = "jpeg"
        if not image_format:
            suffix = path.suffix.lower().removeprefix(".")
            image_format = "jpeg" if suffix == "jpg" else suffix
        if not image_format:
            image_format = "png"

        return ImageData(
            base64_data=encode_to_base64(image_bytes),
            format=image_format,
            placeholder="[image]",
        )
    except (UnidentifiedImageError, OSError) as e:
        logger.debug("Failed to load image from %s: %s", path, e, exc_info=True)
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


def create_multimodal_content(
    text: str, images: list[ImageData], videos: list[VideoData] | None = None
) -> list[dict]:
    """Create multimodal message content with text, images, and videos.

    Args:
        text: Text content of the message
        images: List of ImageData objects
        videos: Optional list of VideoData objects

    Returns:
        List of content blocks in LangChain message format.
    """
    content_blocks = []

    # Add text block
    if text.strip():
        content_blocks.append({"type": "text", "text": text})

    # Add image blocks
    content_blocks.extend(image.to_message_content() for image in images)

    # Add video blocks
    if videos:
        content_blocks.extend(video.to_message_content() for video in videos)

    return content_blocks
