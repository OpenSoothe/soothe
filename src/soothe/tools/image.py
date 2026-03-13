"""Image analysis tools using vision-capable LLMs.

Ported from noesium's image toolkit. No langchain equivalent for vision-model
analysis, OCR, or image comparison.
"""

from __future__ import annotations

import base64
import io

from langchain_core.tools import BaseTool
from pydantic import Field


def _image_to_base64(image_path: str, max_size: int = 1024) -> str:
    """Load an image and convert to base64, resizing if needed.

    Args:
        image_path: Local path or URL to the image.
        max_size: Maximum dimension in pixels.

    Returns:
        Base64-encoded JPEG string.
    """
    from PIL import Image

    if image_path.startswith(("http://", "https://")):
        import requests

        resp = requests.get(image_path, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    else:
        img = Image.open(image_path)

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

    def _run(self, image_path: str, prompt: str = "Describe this image in detail.") -> str:
        from langchain.chat_models import init_chat_model

        b64 = _image_to_base64(image_path)
        model = init_chat_model(f"openai:{self.model_name}")
        msg = model.invoke(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ]
        )
        return str(msg.content)

    async def _arun(self, image_path: str, prompt: str = "Describe this image in detail.") -> str:
        from langchain.chat_models import init_chat_model

        b64 = _image_to_base64(image_path)
        model = init_chat_model(f"openai:{self.model_name}")
        msg = await model.ainvoke(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ]
        )
        return str(msg.content)


class ExtractTextFromImageTool(BaseTool):
    """Extract text (OCR) from an image using a vision-capable LLM."""

    name: str = "extract_text_from_image"
    description: str = "Extract all visible text from an image via OCR. Provide `image_path` (local path or URL)."
    model_name: str = Field(default="gpt-4o")

    def _run(self, image_path: str) -> str:
        from langchain.chat_models import init_chat_model

        b64 = _image_to_base64(image_path)
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
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ]
        )
        return str(msg.content)

    async def _arun(self, image_path: str) -> str:
        from langchain.chat_models import init_chat_model

        b64 = _image_to_base64(image_path)
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
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }
            ]
        )
        return str(msg.content)


def create_image_tools() -> list[BaseTool]:
    """Create image analysis tools.

    Returns:
        List of image analysis `BaseTool` instances.
    """
    return [ImageAnalysisTool(), ExtractTextFromImageTool()]
