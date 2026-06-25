"""Image generation tool for UnifiedAgent."""

import logging

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ImageGenerationInput(BaseModel):
    """Input schema for image generation tool."""

    prompt: str = Field(
        description="A detailed English prompt describing the image to generate. "
        "Translate and refine the user's request into a clear, descriptive prompt."
    )


def create_image_generation_tool(request, user, connection_idx=None) -> StructuredTool:
    """Create a LangChain StructuredTool for image generation.

    Args:
        request: FastAPI request object (for accessing app config and image API)
        user: User object (required by image_generations API)

    Returns:
        StructuredTool for image generation
    """

    async def generate_image(prompt: str) -> str:
        """Generate an image from a text prompt."""
        from open_webui.routers.images import GenerateImageForm, image_generations

        try:
            logger.info(f"[ImageTool] Generating image with prompt: {prompt[:100]}...")

            images = await image_generations(
                request,
                GenerateImageForm(prompt=prompt, connection_idx=connection_idx),
                user,
            )

            if images:
                result = "\n".join(
                    f"![Generated Image]({img['url']})" for img in images
                )
                logger.info(f"[ImageTool] Generated {len(images)} image(s)")
                return result

            return "Image generation completed but no images were returned."

        except Exception as e:
            error_msg = f"Image generation failed: {str(e)}"
            logger.error(f"[ImageTool] {error_msg}")
            return error_msg

    return StructuredTool.from_function(
        coroutine=generate_image,
        name="generate_image",
        description=(
            "Generate an image based on a text prompt. "
            "Use this tool ONLY when the user explicitly requests image creation, "
            "drawing, illustration, or visual content generation. "
            "Do NOT use for general questions or text-based requests. "
            "The prompt should be a detailed English description of the desired image."
        ),
        args_schema=ImageGenerationInput,
    )
