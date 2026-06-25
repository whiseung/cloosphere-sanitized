"""
File Upload Guardrails — utility functions for pre/post-storage file checks.

Pipeline:
  Stage 1 (Pre-Storage):  macro detection
  Stage 2 (Post-Storage): EXIF strip, NSFW detection
  Stage 3 (Text):         existing GuardrailEngine (block only)
  Stage 4 (Classification): LLM-based document classification
"""

import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


# ---------------------------------------------------------------------------
# Error formatting helper
# ---------------------------------------------------------------------------


def format_guardrail_error(details: Optional[dict]) -> str:
    """Format guardrail block details into a human-readable error message.

    Expected details structure (from apply_text_guardrails / apply_text_guardrails_with_llm):
        {
            "guardrail_id": "...",
            "guardrail_name": "Policy Name",
            "violations": [
                {"type": "pii", "pii_type": "email", ...},
                {"type": "blocked_word", "word": "secret", ...},
                {"type": "llm_judge", "matched": "Content blocked by LLM judge", ...},
            ]
        }
    """
    if not details:
        return "File blocked by content guardrail"

    guardrail_name = details.get("guardrail_name", "")
    violations = details.get("violations", [])

    if not violations:
        if guardrail_name:
            return f"Guardrail '{guardrail_name}': File blocked by content guardrail"
        return "File blocked by content guardrail"

    # Group violations by type
    pii_types: list[str] = []
    blocked_words: list[str] = []
    llm_judge = False

    for v in violations:
        vtype = v.get("type", "")
        if vtype == "pii":
            name = v.get("pii_type", "pii")
            if name not in pii_types:
                pii_types.append(name)
        elif vtype == "custom_pattern":
            name = v.get("pattern_name", "custom_pattern")
            if name not in pii_types:
                pii_types.append(name)
        elif vtype == "blocked_word":
            word = v.get("word", "")
            if word and word not in blocked_words:
                blocked_words.append(word)
        elif vtype == "llm_judge":
            llm_judge = True

    parts: list[str] = []
    if pii_types:
        types_str = ", ".join(pii_types[:10])
        pii_count = sum(
            1 for v in violations if v.get("type") in ("pii", "custom_pattern")
        )
        parts.append(f"PII detected: {types_str} ({pii_count}건)")
    if blocked_words:
        words_str = ", ".join(f"'{w}'" for w in blocked_words[:5])
        bw_count = sum(1 for v in violations if v.get("type") == "blocked_word")
        parts.append(f"Blocked word(s): {words_str} ({bw_count}건)")
    if llm_judge:
        parts.append("Content blocked by LLM judge")

    detail_str = "; ".join(parts) if parts else "content violation detected"

    if guardrail_name:
        return f"Guardrail '{guardrail_name}': {detail_str}"
    return f"File blocked: {detail_str}"


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class FileGuardrailResult:
    passed: bool
    check_name: str  # "macro_detection", "exif_strip", "nsfw_detection", "text_guardrail", "classification"
    action: str  # "allow", "flag", "block"
    details: Optional[dict] = field(default=None)
    error: Optional[str] = field(default=None)


# ---------------------------------------------------------------------------
# 1-1. Macro Detection (oletools)
# ---------------------------------------------------------------------------

MACRO_EXTENSIONS = {".doc", ".docm", ".xls", ".xlsm", ".ppt", ".pptm"}


def detect_macros(file_content: bytes, filename: str) -> FileGuardrailResult:
    """Detect VBA macros in Office files using oletools."""
    ext = Path(filename).suffix.lower()
    if ext not in MACRO_EXTENSIONS:
        return FileGuardrailResult(
            passed=True, check_name="macro_detection", action="allow"
        )

    try:
        from oletools.olevba import VBA_Parser

        vba_parser = VBA_Parser(filename, data=file_content)
        if vba_parser.detect_vba_macros():
            macro_info = []
            for vba_filename, stream_path, vba_code in vba_parser.extract_macros():
                macro_info.append(
                    {
                        "filename": vba_filename,
                        "stream": stream_path,
                        "code_preview": vba_code[:200] if vba_code else "",
                    }
                )
            vba_parser.close()
            return FileGuardrailResult(
                passed=False,
                check_name="macro_detection",
                action="block",  # overridden by config
                details={"macros_found": len(macro_info), "macros": macro_info[:5]},
            )
        vba_parser.close()
    except ImportError:
        log.warning("oletools not installed — macro detection skipped")
        return FileGuardrailResult(
            passed=True,
            check_name="macro_detection",
            action="allow",
            error="oletools not installed",
        )
    except Exception as e:
        log.error(f"Macro detection error — flagging file for review: {e}")
        return FileGuardrailResult(
            passed=True,
            check_name="macro_detection",
            action="flag",
            details={
                "flagged_reason": "Macro detection failed, requires manual review"
            },
            error=str(e),
        )

    return FileGuardrailResult(
        passed=True, check_name="macro_detection", action="allow"
    )


# ---------------------------------------------------------------------------
# 1-2. EXIF Metadata Stripping (Pillow)
# ---------------------------------------------------------------------------

EXIF_EXTENSIONS = {".jpg", ".jpeg", ".tiff", ".tif", ".webp"}


def strip_exif_metadata(file_path: str) -> FileGuardrailResult:
    """Strip EXIF metadata from images in-place using Pillow."""
    ext = Path(file_path).suffix.lower()
    if ext not in EXIF_EXTENSIONS:
        return FileGuardrailResult(passed=True, check_name="exif_strip", action="allow")

    try:
        from PIL import Image

        img = Image.open(file_path)
        exif_data = img.getexif()
        if not exif_data:
            img.close()
            return FileGuardrailResult(
                passed=True,
                check_name="exif_strip",
                action="allow",
                details={"had_exif": False},
            )

        # Re-save without EXIF
        img_data = img.copy()
        img.close()
        img_data.save(file_path, exif=b"")
        img_data.close()

        return FileGuardrailResult(
            passed=True,
            check_name="exif_strip",
            action="allow",
            details={"had_exif": True, "stripped": True},
        )
    except Exception as e:
        log.error(f"EXIF stripping error — flagging file for review: {e}")
        return FileGuardrailResult(
            passed=True,
            check_name="exif_strip",
            action="flag",
            details={"flagged_reason": "EXIF stripping failed, requires manual review"},
            error=str(e),
        )


# ---------------------------------------------------------------------------
# 1-3. NSFW Image Detection (LLM Vision)
# ---------------------------------------------------------------------------

IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/tiff",
}


async def detect_nsfw_via_llm(
    app,
    file_content: bytes,
    content_type: str,
    model_id: str,
    prompt: str,
    pass_examples: list,
    block_examples: list,
) -> FileGuardrailResult:
    """Detect NSFW content via LLM Vision model."""
    if content_type not in IMAGE_CONTENT_TYPES:
        return FileGuardrailResult(
            passed=True, check_name="nsfw_detection", action="allow"
        )

    if not model_id:
        return FileGuardrailResult(
            passed=True,
            check_name="nsfw_detection",
            action="allow",
            error="No NSFW model configured",
        )

    try:
        from extension_modules.utils.llm import create_llm, get_model_config_from_app
        from langchain_core.messages import HumanMessage, SystemMessage

        model_config = get_model_config_from_app(app, model_id)
        if not model_config:
            return FileGuardrailResult(
                passed=True,
                check_name="nsfw_detection",
                action="allow",
                error=f"Model config not found: {model_id}",
            )

        llm = create_llm(model_config)

        # Build few-shot prompt
        system_parts = [prompt]
        if pass_examples:
            system_parts.append("\nExamples of SAFE images (respond PASS):")
            for ex in pass_examples:
                system_parts.append(f"- {ex}")
        if block_examples:
            system_parts.append("\nExamples of UNSAFE images (respond BLOCK):")
            for ex in block_examples:
                system_parts.append(f"- {ex}")
        system_parts.append(
            "\nRespond with ONLY 'PASS' if the image is safe, or 'BLOCK' if inappropriate."
        )

        b64 = base64.b64encode(file_content).decode("utf-8")
        messages = [
            SystemMessage(content="\n".join(system_parts)),
            HumanMessage(
                content=[
                    {"type": "text", "text": "Analyze this image:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{content_type};base64,{b64}"},
                    },
                ]
            ),
        ]

        response = await llm.ainvoke(messages)
        result_text = response.content.strip().upper()

        if "BLOCK" in result_text:
            return FileGuardrailResult(
                passed=False,
                check_name="nsfw_detection",
                action="block",
                details={"raw_response": response.content.strip()},
            )

        return FileGuardrailResult(
            passed=True,
            check_name="nsfw_detection",
            action="allow",
            details={"raw_response": response.content.strip()},
        )
    except Exception as e:
        log.error(f"NSFW detection error — flagging file for review: {e}")
        return FileGuardrailResult(
            passed=True,
            check_name="nsfw_detection",
            action="flag",
            details={"flagged_reason": "NSFW detection failed, requires manual review"},
            error=str(e),
        )


# ---------------------------------------------------------------------------
# 1-4. Text Guardrails (existing GuardrailEngine, block-only)
# ---------------------------------------------------------------------------


def apply_text_guardrails(text: str, guardrail_ids: list[str]) -> FileGuardrailResult:
    """Apply existing guardrail rules to document text. Block-only strategy (rule-based only)."""
    from open_webui.models.guardrails import Guardrails
    from open_webui.utils.guardrails import GuardrailEngine

    all_violations = []

    for gid in guardrail_ids:
        guardrail = Guardrails.get_guardrail_by_id(gid)
        if not guardrail:
            log.warning(f"Guardrail not found: {gid}")
            continue

        config = guardrail.model_dump()
        # Force block strategy for file uploads
        config["pii_strategy"] = "block"
        config["apply_to_input"] = True

        engine = GuardrailEngine(config)
        _, violations, blocked = engine.process_text(text, is_input=True)

        if violations:
            all_violations.extend(
                [
                    {**v, "guardrail_id": gid, "guardrail_name": guardrail.name}
                    for v in violations
                ]
            )

        if blocked:
            return FileGuardrailResult(
                passed=False,
                check_name="text_guardrail",
                action="block",
                details={
                    "guardrail_id": gid,
                    "guardrail_name": guardrail.name,
                    "violations": all_violations[:10],
                },
            )

    if all_violations:
        return FileGuardrailResult(
            passed=False,
            check_name="text_guardrail",
            action="block",
            details={"violations": all_violations[:10]},
        )

    return FileGuardrailResult(passed=True, check_name="text_guardrail", action="allow")


async def apply_text_guardrails_with_llm(
    app, text: str, guardrail_ids: list[str]
) -> FileGuardrailResult:
    """Apply guardrail rules + LLM Judge to document text. Block-only strategy."""
    # First, run rule-based guardrails
    result = apply_text_guardrails(text, guardrail_ids)
    if result.action == "block":
        return result

    # Then, run LLM Judge for configs that have it enabled
    from open_webui.models.guardrails import Guardrails

    for gid in guardrail_ids:
        guardrail = Guardrails.get_guardrail_by_id(gid)
        if not guardrail:
            continue

        config = guardrail.model_dump()
        if not config.get("llm_judge_enabled"):
            continue

        model_id = config.get("llm_judge_model")
        if not model_id:
            log.warning(f"LLM Judge enabled but no model configured for {gid}")
            continue

        try:
            from extension_modules.utils.llm import create_llm_from_app
            from langchain_core.messages import HumanMessage

            llm = create_llm_from_app(app, model_id, temperature=0, max_tokens=100)
            if not llm:
                log.warning(f"LLM Judge model not found: {model_id}")
                continue

            # Build prompt (same pattern as pii_detector.LLMJudge)
            prompt_text = config.get("llm_judge_prompt") or (
                "You are a content moderator. Evaluate the content and respond "
                'with only "PASS" or "BLOCK".'
            )
            examples_section = ""
            pass_examples = config.get("llm_judge_pass_examples", [])
            block_examples = config.get("llm_judge_block_examples", [])
            if pass_examples:
                examples_section += "\n\nExamples of content that should PASS:\n"
                for i, ex in enumerate(pass_examples, 1):
                    examples_section += f"{i}. {ex}\n"
            if block_examples:
                examples_section += "\n\nExamples of content that should be BLOCKED:\n"
                for i, ex in enumerate(block_examples, 1):
                    examples_section += f"{i}. {ex}\n"

            # Sample text for large documents
            sample = sample_document_text(text, max_chars=4000)

            full_prompt = (
                f"{prompt_text}{examples_section}\n\n"
                f"Content to evaluate:\n---\n{sample}\n---\n\n"
                f'Respond with only "PASS" or "BLOCK".'
            )

            response = await llm.ainvoke([HumanMessage(content=full_prompt)])
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )

            response_lower = content.lower().strip()
            if "block" in response_lower:
                return FileGuardrailResult(
                    passed=False,
                    check_name="text_guardrail",
                    action="block",
                    details={
                        "guardrail_id": gid,
                        "guardrail_name": guardrail.name,
                        "violations": [
                            {
                                "type": "llm_judge",
                                "matched": "Content blocked by LLM judge",
                                "guardrail_id": gid,
                                "guardrail_name": guardrail.name,
                            }
                        ],
                    },
                )

        except Exception as e:
            log.error(f"LLM Judge error for file guardrail {gid}: {e}")
            return FileGuardrailResult(
                passed=True,
                check_name="text_guardrail",
                action="flag",
                details={
                    "flagged_reason": f"LLM Judge failed for {guardrail.name}, requires manual review"
                },
                error=str(e),
            )

    return result


# ---------------------------------------------------------------------------
# 1-5. Document Classification (LLM + Custom Prompt + Few-shot)
# ---------------------------------------------------------------------------


def sample_document_text(text: str, max_chars: int = 8000) -> str:
    """Sample head/middle/tail from large documents."""
    if len(text) <= max_chars:
        return text
    third = max_chars // 3
    head = text[:third]
    mid_start = (len(text) - third) // 2
    middle = text[mid_start : mid_start + third]
    tail = text[-third:]
    return f"{head}\n\n[...]\n\n{middle}\n\n[...]\n\n{tail}"


async def classify_document(
    app,
    text: str,
    model_id: str,
    prompt: str,
    categories: list[dict],
    pass_examples: list,
    block_examples: list,
    max_chars: int,
) -> FileGuardrailResult:
    """Classify document sensitivity via LLM with custom prompt and few-shot."""
    if not model_id:
        return FileGuardrailResult(
            passed=True,
            check_name="classification",
            action="allow",
            details={"category": "UNCLASSIFIED", "error": "No model configured"},
        )

    if not text or not text.strip():
        return FileGuardrailResult(
            passed=True,
            check_name="classification",
            action="allow",
            details={"category": "UNCLASSIFIED", "reason": "Empty document"},
        )

    try:
        from extension_modules.utils.llm import create_llm, get_model_config_from_app
        from langchain_core.messages import HumanMessage, SystemMessage

        model_config = get_model_config_from_app(app, model_id)
        if not model_config:
            return FileGuardrailResult(
                passed=True,
                check_name="classification",
                action="allow",
                details={
                    "category": "UNCLASSIFIED",
                    "error": f"Model config not found: {model_id}",
                },
            )

        llm = create_llm(model_config)
        sampled = sample_document_text(text, max_chars)

        # Build categories JSON for prompt
        categories_json = json.dumps(
            [
                {
                    "id": c["id"],
                    "name": c.get("name", c["id"]),
                    "description": c.get("description", ""),
                }
                for c in categories
            ],
            ensure_ascii=False,
            indent=2,
        )

        # Build system prompt
        system_prompt = prompt.replace("{categories}", categories_json)

        # Build few-shot examples
        few_shot_parts = []
        if pass_examples:
            few_shot_parts.append("Examples of non-sensitive documents:")
            for ex in pass_examples:
                few_shot_parts.append(
                    f'Document: "{ex.get("text", "")}"\nClassification: {{"category": "{ex.get("expected", "PUBLIC")}", "confidence": 0.9, "reason": "Non-sensitive content"}}'
                )
        if block_examples:
            few_shot_parts.append("\nExamples of sensitive documents:")
            for ex in block_examples:
                few_shot_parts.append(
                    f'Document: "{ex.get("text", "")}"\nClassification: {{"category": "{ex.get("expected", "RESTRICTED")}", "confidence": 0.9, "reason": "Sensitive content"}}'
                )

        messages = [SystemMessage(content=system_prompt)]
        if few_shot_parts:
            messages.append(HumanMessage(content="\n".join(few_shot_parts)))
        messages.append(HumanMessage(content=f"Classify this document:\n\n{sampled}"))

        response = await llm.ainvoke(messages)
        raw = response.content.strip()

        # Parse JSON response
        parsed = _parse_classification_response(raw, categories)
        category_id = parsed.get("category", "UNCLASSIFIED")

        # Find action for this category
        action = "allow"
        for cat in categories:
            if cat["id"] == category_id:
                action = cat.get("action", "allow")
                break

        return FileGuardrailResult(
            passed=(action != "block"),
            check_name="classification",
            action=action,
            details={
                "category": category_id,
                "confidence": parsed.get("confidence"),
                "reason": parsed.get("reason"),
                "model": model_id,
            },
        )
    except Exception as e:
        log.error(f"Document classification error — flagging file: {e}")
        return FileGuardrailResult(
            passed=True,
            check_name="classification",
            action="flag",
            details={
                "category": "UNCLASSIFIED",
                "flagged_reason": "Classification failed, requires manual review",
            },
            error=str(e),
        )


def _parse_classification_response(raw: str, categories: list[dict]) -> dict:
    """Parse LLM classification response, extracting JSON."""
    # Try direct JSON parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON from markdown code block
    import re

    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding JSON object in text
    json_match = re.search(r"\{[^{}]*\}", raw)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Fallback: check if any category ID appears as a whole word in the response
    for cat in categories:
        pattern = r"\b" + re.escape(cat["id"].upper()) + r"\b"
        if re.search(pattern, raw.upper()):
            return {
                "category": cat["id"],
                "confidence": 0.5,
                "reason": "Extracted from text (word boundary match)",
            }

    return {
        "category": "UNCLASSIFIED",
        "confidence": 0.0,
        "reason": "Could not parse response",
    }


# ---------------------------------------------------------------------------
# 1-6. Orchestrators
# ---------------------------------------------------------------------------


async def run_pre_storage_guardrails(
    app, file_content: bytes, filename: str
) -> list[FileGuardrailResult]:
    """Stage 1: Pre-storage checks (macro detection)."""
    results = []

    if getattr(app.state.config, "FILE_GUARDRAIL_MACRO_ENABLED", False):
        result = detect_macros(file_content, filename)
        # Apply configured action
        action = getattr(app.state.config, "FILE_GUARDRAIL_MACRO_ACTION", "block")
        result.action = action if not result.passed else "allow"
        results.append(result)

    return results


async def run_post_storage_guardrails(
    app,
    file_path: str,
    filename: str,
    content_type: str,
    file_content: bytes,
) -> list[FileGuardrailResult]:
    """Stage 2: Post-storage checks (EXIF strip, NSFW detection)."""
    results = []

    # EXIF stripping
    if getattr(app.state.config, "FILE_GUARDRAIL_EXIF_ENABLED", False):
        result = strip_exif_metadata(file_path)
        results.append(result)

    # NSFW detection
    if getattr(app.state.config, "FILE_GUARDRAIL_NSFW_ENABLED", False):
        model_id = getattr(app.state.config, "FILE_GUARDRAIL_NSFW_MODEL", "")
        prompt = getattr(
            app.state.config,
            "FILE_GUARDRAIL_NSFW_PROMPT",
            "Analyze this image for inappropriate content. Respond with ONLY 'PASS' or 'BLOCK'.",
        )
        pass_examples = getattr(
            app.state.config, "FILE_GUARDRAIL_NSFW_PASS_EXAMPLES", []
        )
        block_examples = getattr(
            app.state.config, "FILE_GUARDRAIL_NSFW_BLOCK_EXAMPLES", []
        )

        result = await detect_nsfw_via_llm(
            app,
            file_content,
            content_type,
            model_id,
            prompt,
            pass_examples,
            block_examples,
        )
        results.append(result)

    return results


async def run_text_guardrails(
    app, text: str, guardrail_ids: list[str]
) -> FileGuardrailResult:
    """Stage 3: Text guardrails (rule-based + LLM Judge, block-only)."""
    return await apply_text_guardrails_with_llm(app, text, guardrail_ids)


async def run_classification(app, text: str) -> FileGuardrailResult:
    """Stage 4: Document classification."""
    model_id = getattr(app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_MODEL", "")
    prompt = getattr(
        app.state.config,
        "FILE_GUARDRAIL_CLASSIFICATION_PROMPT",
        "",
    )
    categories = getattr(
        app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_CATEGORIES", []
    )
    pass_examples = getattr(
        app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_PASS_EXAMPLES", []
    )
    block_examples = getattr(
        app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_BLOCK_EXAMPLES", []
    )
    max_chars = getattr(
        app.state.config, "FILE_GUARDRAIL_CLASSIFICATION_MAX_CHARS", 8000
    )

    return await classify_document(
        app,
        text,
        model_id,
        prompt,
        categories,
        pass_examples,
        block_examples,
        max_chars,
    )
