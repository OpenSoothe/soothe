"""Image analysis tools using vision-capable LLMs.

Ported from noesium's image toolkit. No langchain equivalent for vision-model
analysis, OCR, or image comparison.
"""

from __future__ import annotations

import base64
import io
import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool
from pydantic import Field
from soothe_sdk.plugin import plugin

from soothe.toolkits._internal.local_path_resolution import resolve_toolkit_local_path
from soothe.utils.tool_error_handler import tool_error_handler
from soothe.utils.url_validation import validate_url

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _image_to_base64(
    image_path: str,
    max_size: int = 1024,
    *,
    config: Any | None = None,
) -> str:
    """Load an image and convert to base64, resizing if needed.

    Args:
        image_path: Local path or URL to the image.
        max_size: Maximum dimension in pixels.
        config: Optional ``SootheConfig`` for local path sandboxing (IG-316).

    Returns:
        Base64-encoded JPEG string.

    Raises:
        ValueError: If URL is invalid.
        Exception: If image loading fails.
    """
    from PIL import Image

    if image_path.startswith(("http://", "https://")):
        import requests

        # Validate URL
        validated_url, error = validate_url(image_path)
        if error:
            raise ValueError(error)

        resp = requests.get(validated_url, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    else:
        local = resolve_toolkit_local_path(image_path, config=config)
        img = Image.open(local)

    img = img.convert("RGB")
    img.thumbnail((max_size, max_size))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class ImageAnalysisTool(BaseTool):
    """Analyse an image using a vision-capable LLM."""

    name: str = "analyze_image"
    description: str = (
        "Analyse an image using a vision-capable model. "
        "Provide `image_path` (local path or URL) and an optional `prompt` "
        "(default: 'Describe this image in detail')."
    )
    model_name: str = Field(default="gpt-4o")
    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    @tool_error_handler("analyze_image", return_type="str")
    def _run(self, image_path: str, prompt: str = "Describe this image in detail.") -> str:
        b64 = _image_to_base64(image_path, config=self.config)

        # Use config if available (ensures LimitedProviderModelWrapper applied)
        if self.config:
            model = self.config.create_chat_model("image")
        else:
            from langchain.chat_models import init_chat_model

            logger.warning("No config provided, limited_openai wrapper NOT applied")
            model = init_chat_model(f"openai:{self.model_name}")

        msg = model.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ]
        )

        return str(msg.content)

    @tool_error_handler("analyze_image", return_type="str")
    async def _arun(self, image_path: str, prompt: str = "Describe this image in detail.") -> str:
        # IG-143: Add metadata for tracing
        from soothe.middleware._utils import create_llm_call_metadata

        b64 = _image_to_base64(image_path, config=self.config)

        # Use config if available (ensures LimitedProviderModelWrapper applied)
        if self.config:
            model = self.config.create_chat_model("image")
        else:
            from langchain.chat_models import init_chat_model

            logger.warning("No config provided, limited_openai wrapper NOT applied")
            model = init_chat_model(f"openai:{self.model_name}")

        msg = await model.ainvoke(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            config={
                "metadata": create_llm_call_metadata(
                    purpose="vision_analysis",
                    component="tools.image",
                    phase="layer1",
                    image_path=image_path,
                )
            },
        )

        return str(msg.content)


class ExtractTextFromImageTool(BaseTool):
    """Extract text (OCR) from an image using a vision-capable LLM."""

    name: str = "extract_text_from_image"
    description: str = (
        "Extract all visible text from an image via OCR. Provide `image_path` (local path or URL)."
    )
    model_name: str = Field(default="gpt-4o")
    config: Any = Field(default=None, exclude=True)  # SootheConfig for model creation

    @tool_error_handler("extract_text_from_image", return_type="str")
    def _run(self, image_path: str) -> str:
        b64 = _image_to_base64(image_path, config=self.config)

        # Use config if available (ensures LimitedProviderModelWrapper applied)
        if self.config:
            model = self.config.create_chat_model("image")
        else:
            from langchain.chat_models import init_chat_model

            logger.warning("No config provided, limited_openai wrapper NOT applied")
            model = init_chat_model(f"openai:{self.model_name}")

        msg = model.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract ALL text visible in this image. Return only the extracted text.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ]
        )

        return str(msg.content)

    @tool_error_handler("extract_text_from_image", return_type="str")
    async def _arun(self, image_path: str) -> str:
        b64 = _image_to_base64(image_path, config=self.config)

        # Use config if available (ensures LimitedProviderModelWrapper applied)
        if self.config:
            model = self.config.create_chat_model("image")
        else:
            from langchain.chat_models import init_chat_model

            logger.warning("No config provided, limited_openai wrapper NOT applied")
            model = init_chat_model(f"openai:{self.model_name}")

        msg = await model.ainvoke(
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Extract ALL text visible in this image. Return only the extracted text.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ]
        )

        return str(msg.content)


class ImageToolkit:
    """Toolkit for image analysis operations."""

    def __init__(self, config: Any = None) -> None:
        """Initialize the toolkit.

        Args:
            config: SootheConfig instance for model creation (ensures LimitedProviderModelWrapper).
        """
        self._config = config

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of image analysis tool instances.
        """
        return [
            ImageAnalysisTool(config=self._config),
            ExtractTextFromImageTool(config=self._config),
        ]


@plugin(name="image", version="1.0.0", description="Image analysis", trust_level="built-in")
class ImagePlugin:
    """Image analysis tools plugin.

    Provides analyze_image and extract_text_from_image tools.
    """

    def __init__(self) -> None:
        """Initialize the plugin."""
        self._tools: list[BaseTool] = []

    async def on_load(self, context) -> None:
        """Initialize tools.

        Args:
            context: Plugin context with config and logger.
        """
        toolkit = ImageToolkit(config=context.soothe_config)
        self._tools = toolkit.get_tools()

        context.logger.info("Loaded %d image tools", len(self._tools))

    def get_tools(self) -> list[BaseTool]:
        """Get list of langchain tools.

        Returns:
            List of image analysis tool instances.
        """
        return self._tools
