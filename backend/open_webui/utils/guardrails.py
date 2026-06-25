import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


####################
# Effective Guardrail IDs (공통 수집 함수)
####################


def get_effective_guardrail_ids(
    user_id: str,
    request: Any,
    source_guardrail_ids: Optional[List[str]] = None,
) -> List[str]:
    """Collect and merge guardrail IDs from all levels (deduplicated).

    Priority order (all merged, not overridden):
      1. Source level — agent guardrail_ids (chat) or CODE_GATEWAY_GUARDRAIL_IDS (code gateway)
      2. Group level — group.meta.chat_guardrail_id
      3. Organization level — organization.meta.guardrail_ids
      4. Global level — GLOBAL_GUARDRAIL_IDS (if ENABLE_GLOBAL_GUARDRAIL is true)

    Returns:
        Deduplicated list of guardrail IDs.
    """
    ids: List[str] = []

    # 1. Source-level guardrails
    if source_guardrail_ids:
        ids.extend(source_guardrail_ids)

    # 2. Group-level guardrails
    try:
        if user_id:
            from open_webui.models.groups import Groups

            user_groups = Groups.get_groups_by_member_id(user_id)
            for group in user_groups:
                group_guardrail_id = (group.meta or {}).get("chat_guardrail_id")
                if group_guardrail_id and group_guardrail_id not in ids:
                    ids.append(group_guardrail_id)
    except Exception:
        log.debug("[Guardrail] Failed to resolve group-level guardrails", exc_info=True)

    # 3. Organization-level guardrails
    try:
        if user_id:
            org_ids = _get_org_guardrail_ids(user_id, request=request)
            for gid in org_ids:
                if gid not in ids:
                    ids.append(gid)
    except Exception:
        log.debug("[Guardrail] Failed to resolve org-level guardrails", exc_info=True)

    # 4. Global guardrails
    #    Skip if the user belongs to an org unit that has follow_global_guardrail=False
    #    (org-level already handled global inclusion via _get_org_guardrail_ids)
    opts_out = _user_org_opts_out_global(user_id)
    log.info(f"[Guardrail] user_id={user_id}, org_opts_out_global={opts_out}")
    if not opts_out:
        try:
            config = request.app.state.config
            enabled = getattr(config, "ENABLE_GLOBAL_GUARDRAIL", None)
            if hasattr(enabled, "value"):
                enabled = enabled.value
            if enabled:
                global_ids = getattr(config, "GLOBAL_GUARDRAIL_IDS", None)
                if hasattr(global_ids, "value"):
                    global_ids = global_ids.value
                if global_ids:
                    for gid in global_ids:
                        if gid not in ids:
                            ids.append(gid)
        except Exception:
            log.debug("[Guardrail] Failed to resolve global guardrails", exc_info=True)

    return ids


def _get_org_guardrail_ids(user_id: str, request: Any = None) -> List[str]:
    """Resolve guardrail IDs from user's organizational unit.

    Looks up the OrganizationalUnit the user belongs to, then reads
    ``unit.meta.guardrail_ids`` (list of str).
    If ``unit.meta.follow_global_guardrail`` is true, global guardrail
    IDs are also included.
    """
    from open_webui.internal.db import get_db
    from open_webui.models.organization import OrganizationalUnit, OrganizationalUnits
    from open_webui.models.users import Users
    from sqlalchemy import String, cast

    user = Users.get_user_by_id(user_id)
    if not user:
        return []

    with get_db() as db:
        # Find the unit the user belongs to (oauth_sub or email match)
        unit = None

        # Try oauth_sub match first
        if getattr(user, "oauth_sub", None):
            unit = (
                db.query(OrganizationalUnit)
                .filter(
                    cast(OrganizationalUnit.member_ids, String).like(
                        f'%"{user.oauth_sub}"%'
                    )
                )
                .first()
            )

        # Fallback to email match via meta.members
        if not unit and user.email:
            all_units = OrganizationalUnits.get_all_organizational_units()
            for u in all_units:
                if u.meta and "members" in u.meta:
                    member_emails = [
                        m.get("email", "").lower()
                        for m in u.meta.get("members", [])
                        if m.get("email")
                    ]
                    if user.email.lower() in member_emails:
                        unit = u
                        break

        if not unit:
            return []

        unit_meta = unit.meta if hasattr(unit, "meta") else {}
        if isinstance(unit, OrganizationalUnit):
            # DB row object — read meta from column
            unit_meta = unit.meta or {}
        elif hasattr(unit, "meta"):
            unit_meta = unit.meta or {}
        else:
            unit_meta = {}

        ids: List[str] = []

        # "전역 설정 따름" — include global guardrail IDs (default: True)
        if unit_meta.get("follow_global_guardrail", True) and request:
            try:
                config = request.app.state.config
                global_ids = getattr(config, "GLOBAL_GUARDRAIL_IDS", None)
                if hasattr(global_ids, "value"):
                    global_ids = global_ids.value
                if global_ids:
                    ids.extend(global_ids)
            except Exception:
                pass

        # Unit's own guardrail IDs
        unit_ids = unit_meta.get("guardrail_ids", [])
        if isinstance(unit_ids, list):
            for gid in unit_ids:
                if gid not in ids:
                    ids.append(gid)

        return ids


def _user_org_opts_out_global(user_id: str) -> bool:
    """Return True if the user belongs to an org unit with follow_global_guardrail=False."""
    try:
        from open_webui.internal.db import get_db
        from open_webui.models.organization import (
            OrganizationalUnit,
            OrganizationalUnits,
        )
        from open_webui.models.users import Users
        from sqlalchemy import String, cast

        user = Users.get_user_by_id(user_id)
        if not user:
            return False

        with get_db() as db:
            unit = None
            if getattr(user, "oauth_sub", None):
                unit = (
                    db.query(OrganizationalUnit)
                    .filter(
                        cast(OrganizationalUnit.member_ids, String).like(
                            f'%"{user.oauth_sub}"%'
                        )
                    )
                    .first()
                )
            if not unit and user.email:
                all_units = OrganizationalUnits.get_all_organizational_units()
                for u in all_units:
                    if u.meta and "members" in u.meta:
                        member_emails = [
                            m.get("email", "").lower()
                            for m in u.meta.get("members", [])
                            if m.get("email")
                        ]
                        if user.email.lower() in member_emails:
                            unit = u
                            break
            if not unit:
                return False

            unit_meta = unit.meta or {} if hasattr(unit, "meta") else {}
            follow = unit_meta.get("follow_global_guardrail")
            return follow is False
    except Exception as e:
        log.info(f"[Guardrail] _user_org_opts_out_global exception: {e}")
        return False


####################
# PII Patterns
####################

PII_PATTERNS: Dict[str, Dict[str, Any]] = {
    "email": {
        "pattern": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "description": "Email addresses (e.g., user@domain.com)",
        "mask_func": lambda m: f"{m.group(0)[0]}***@***{m.group(0).split('@')[1][-4:] if len(m.group(0).split('@')[1]) > 4 else m.group(0).split('@')[1]}",
    },
    "credit_card": {
        "pattern": r"(?<!\d)(?:\d{4}[- ]?){3}\d{4}(?!\d)",
        "description": "Credit card numbers (validated with Luhn algorithm)",
        "mask_func": lambda m: f"****-****-****-{re.sub(r'[- ]', '', m.group(0))[-4:]}",
        "validator": lambda s: luhn_check(re.sub(r"[- ]", "", s)),
    },
    "ip": {
        "pattern": r"(?<!\d)(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?!\d)",
        "description": "IPv4 addresses (e.g., 192.168.1.1)",
        "mask_func": lambda m: f"{m.group(0).split('.')[0]}.***.***.***",
    },
    "mac": {
        "pattern": r"([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})",
        "description": "MAC addresses (e.g., 00:1A:2B:3C:4D:5E)",
        "mask_func": lambda m: f"**:**:**:**:{m.group(0)[-5:]}",
    },
    "url": {
        "pattern": r"https?://[^\s<>\"']+",
        "description": "URLs (http/https links)",
        "mask_func": lambda m: "[URL_MASKED]",
    },
    "api_key": {
        "pattern": r"sk-[a-zA-Z0-9]{20,}",
        "description": "API keys (e.g., sk-xxx pattern)",
        "mask_func": lambda m: f"sk-****{m.group(0)[-4:]}",
    },
}


def luhn_check(card_number: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    try:
        digits = [int(d) for d in card_number if d.isdigit()]
        if len(digits) < 13:
            return False

        checksum = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0
    except Exception:
        return False


####################
# Guardrail Violation
####################


class GuardrailViolation(Exception):
    """Exception raised when guardrail blocks content."""

    def __init__(self, message: str, violations: List[dict] = None):
        self.message = message
        self.violations = violations or []
        super().__init__(self.message)


####################
# Guardrail Engine
####################


class GuardrailEngine:
    """Engine for processing guardrail rules."""

    def __init__(self, config: dict):
        """
        Initialize guardrail engine with configuration.

        Args:
            config: Guardrail configuration dict with keys:
                - pii_types: List of PII types to detect
                - pii_strategy: Strategy for handling PII (block, redact, mask, hash)
                - custom_patterns: List of custom regex patterns
                - blocked_words: List of blocked words
                - apply_to_input: Whether to apply to input
                - apply_to_output: Whether to apply to output
                - llm_judge_enabled: Whether LLM judge is enabled
                - llm_judge_model: Model to use for LLM judge
                - llm_judge_prompt: Prompt for LLM judge
                - llm_judge_pass_examples: Examples of passing content
                - llm_judge_block_examples: Examples of blocked content
        """
        self.config = config
        self.pii_types = config.get("pii_types", [])
        self.pii_strategy = config.get("pii_strategy", "redact")
        self.custom_patterns = config.get("custom_patterns", [])
        self.blocked_words = config.get("blocked_words", [])
        self.apply_to_input = config.get("apply_to_input", True)
        self.apply_to_output = config.get("apply_to_output", False)

        # LLM Judge settings
        self.llm_judge_enabled = config.get("llm_judge_enabled", False)
        self.llm_judge_model = config.get("llm_judge_model")
        self.llm_judge_prompt = config.get("llm_judge_prompt")
        self.llm_judge_pass_examples = config.get("llm_judge_pass_examples", [])
        self.llm_judge_block_examples = config.get("llm_judge_block_examples", [])
        self.llm_judge_apply_to_input = config.get("llm_judge_apply_to_input", True)
        self.llm_judge_apply_to_output = config.get("llm_judge_apply_to_output", False)

    def process_text(
        self, text: str, is_input: bool = True
    ) -> Tuple[str, List[dict], bool]:
        """
        Process text through guardrail rules.

        Args:
            text: Text to process
            is_input: Whether this is input (True) or output (False)

        Returns:
            Tuple of (processed_text, violations, blocked)
        """
        # Check if we should process this direction
        if is_input and not self.apply_to_input:
            return text, [], False
        if not is_input and not self.apply_to_output:
            return text, [], False

        violations = []
        processed_text = text
        blocked = False

        # 1. Detect and process PII
        for pii_type in self.pii_types:
            if pii_type in PII_PATTERNS:
                pii_info = PII_PATTERNS[pii_type]
                pattern = pii_info["pattern"]
                matches = list(re.finditer(pattern, processed_text))

                for match in matches:
                    matched_text = match.group(0)

                    # Validate if validator exists
                    validator = pii_info.get("validator")
                    if validator and not validator(matched_text):
                        continue

                    violations.append(
                        {
                            "type": "pii",
                            "pii_type": pii_type,
                            "matched": matched_text,
                            "start": match.start(),
                            "end": match.end(),
                        }
                    )

        # 2. Detect custom patterns
        for custom in self.custom_patterns:
            pattern_name = custom.get("name", "custom")
            pattern = custom.get("pattern")
            if pattern:
                try:
                    matches = list(re.finditer(pattern, processed_text))
                    for match in matches:
                        violations.append(
                            {
                                "type": "custom_pattern",
                                "pattern_name": pattern_name,
                                "matched": match.group(0),
                                "start": match.start(),
                                "end": match.end(),
                            }
                        )
                except re.error as e:
                    log.warning(f"Invalid regex pattern '{pattern}': {e}")

        # 3. Detect blocked words
        for word in self.blocked_words:
            if word.lower() in text.lower():
                # Find all occurrences
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                for match in pattern.finditer(processed_text):
                    violations.append(
                        {
                            "type": "blocked_word",
                            "word": word,
                            "matched": match.group(0),
                            "start": match.start(),
                            "end": match.end(),
                        }
                    )

        # 4. Apply strategy if violations found
        if violations:
            if self.pii_strategy == "block":
                blocked = True
            elif self.pii_strategy == "log":
                pass  # 탐지만, 텍스트 미수정, 비차단
            else:
                processed_text = self._apply_strategy(processed_text, violations)

        return processed_text, violations, blocked

    def _apply_strategy(self, text: str, violations: List[dict]) -> str:
        """Apply the configured strategy to handle violations."""
        # Sort violations by start position in reverse order to process from end
        sorted_violations = sorted(
            violations, key=lambda v: v.get("start", 0), reverse=True
        )

        for violation in sorted_violations:
            start = violation.get("start", 0)
            end = violation.get("end", 0)
            matched = violation.get("matched", "")
            v_type = violation.get("type")

            if self.pii_strategy == "redact":
                if v_type == "pii":
                    replacement = (
                        f"[REDACTED_{violation.get('pii_type', 'PII').upper()}]"
                    )
                elif v_type == "custom_pattern":
                    replacement = (
                        f"[REDACTED_{violation.get('pattern_name', 'PATTERN').upper()}]"
                    )
                elif v_type == "blocked_word":
                    replacement = "[REDACTED]"
                else:
                    replacement = "[REDACTED]"

            elif self.pii_strategy == "mask":
                if v_type == "pii" and violation.get("pii_type") in PII_PATTERNS:
                    pii_info = PII_PATTERNS[violation["pii_type"]]
                    mask_func = pii_info.get("mask_func")
                    if mask_func:
                        try:
                            # Create a match object for the mask function
                            match = re.match(re.escape(matched), matched)
                            if match:
                                replacement = mask_func(
                                    re.search(pii_info["pattern"], matched)
                                )
                            else:
                                replacement = "*" * len(matched)
                        except Exception:
                            replacement = "*" * len(matched)
                    else:
                        replacement = "*" * len(matched)
                else:
                    replacement = "*" * len(matched)

            elif self.pii_strategy == "hash":
                hash_value = hashlib.sha256(matched.encode()).hexdigest()[:12]
                if v_type == "pii":
                    replacement = (
                        f"<{violation.get('pii_type', 'pii')}_hash:{hash_value}>"
                    )
                elif v_type == "custom_pattern":
                    replacement = f"<{violation.get('pattern_name', 'pattern')}_hash:{hash_value}>"
                else:
                    replacement = f"<hash:{hash_value}>"
            else:
                # Default to redact
                replacement = "[REDACTED]"

            text = text[:start] + replacement + text[end:]

        return text

    async def llm_judge(
        self, text: str, is_input: bool = True, generate_func: callable = None
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Use LLM to judge if content is appropriate.

        Args:
            text: Text to judge
            is_input: Whether this is input (True) or output (False)
            generate_func: Async function to generate LLM response

        Returns:
            Tuple of (passed, reason, raw_response)
        """
        if not self.llm_judge_enabled:
            return True, "LLM judge not enabled", None

        if not self.llm_judge_model:
            return True, "LLM judge model not configured", None

        if not generate_func:
            return True, "Generate function not provided", None

        # Check if we should judge this direction
        if is_input and not self.llm_judge_apply_to_input:
            return True, "LLM judge not applied to input", None
        if not is_input and not self.llm_judge_apply_to_output:
            return True, "LLM judge not applied to output", None

        # Build the prompt
        prompt = self._build_judge_prompt(text)

        try:
            # Call the generate function
            response = await generate_func(
                model=self.llm_judge_model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0,
            )

            # Parse the response
            response_text = (
                response.get("choices", [{}])[0].get("message", {}).get("content", "")
            )

            # Simple parsing: look for PASS or BLOCK
            response_lower = response_text.lower().strip()
            if "pass" in response_lower and "block" not in response_lower:
                return True, "Content approved by LLM judge", response_text
            elif "block" in response_lower:
                return False, "Content blocked by LLM judge", response_text
            else:
                # Default to pass if unclear
                return (
                    True,
                    "LLM judge response unclear, defaulting to pass",
                    response_text,
                )

        except Exception as e:
            log.error(f"LLM judge error: {e}")
            return True, f"LLM judge error: {str(e)}", None

    def _build_judge_prompt(self, text: str) -> str:
        """Build the prompt for LLM judge."""
        base_prompt = (
            self.llm_judge_prompt
            or """You are a content moderator. Evaluate the following content and respond with either "PASS" if the content is appropriate, or "BLOCK" if it should be blocked.

Be strict about blocking harmful, inappropriate, or policy-violating content."""
        )

        examples_section = ""

        if self.llm_judge_pass_examples:
            examples_section += "\n\nExamples of content that should PASS:\n"
            for i, example in enumerate(self.llm_judge_pass_examples, 1):
                examples_section += f"{i}. {example}\n"

        if self.llm_judge_block_examples:
            examples_section += "\n\nExamples of content that should be BLOCKED:\n"
            for i, example in enumerate(self.llm_judge_block_examples, 1):
                examples_section += f"{i}. {example}\n"

        return f"""{base_prompt}
{examples_section}

Content to evaluate:
---
{text}
---

Respond with only "PASS" or "BLOCK"."""


def process_guardrails(
    guardrail_configs: List[dict], text: str, is_input: bool = True
) -> Tuple[str, List[dict], bool, Optional[str]]:
    """
    Process text through multiple guardrail configurations.

    Args:
        guardrail_configs: List of guardrail configuration dicts
        text: Text to process
        is_input: Whether this is input or output

    Returns:
        Tuple of (processed_text, all_violations, blocked, block_reason)
    """
    all_violations = []
    processed_text = text
    blocked = False
    block_reason = None

    for config in guardrail_configs:
        engine = GuardrailEngine(config)
        processed_text, violations, is_blocked = engine.process_text(
            processed_text, is_input
        )
        all_violations.extend(violations)

        if is_blocked:
            blocked = True
            block_reason = f"Blocked by guardrail: {config.get('name', 'Unknown')}"
            break

    return processed_text, all_violations, blocked, block_reason


async def process_guardrails_with_llm_judge(
    guardrail_configs: List[dict],
    text: str,
    is_input: bool = True,
    generate_func: callable = None,
) -> Tuple[str, List[dict], bool, Optional[str]]:
    """
    Process text through multiple guardrail configurations including LLM judge.

    Args:
        guardrail_configs: List of guardrail configuration dicts
        text: Text to process
        is_input: Whether this is input or output
        generate_func: Async function to generate LLM response

    Returns:
        Tuple of (processed_text, all_violations, blocked, block_reason)
    """
    # First, process rule-based guardrails
    processed_text, all_violations, blocked, block_reason = process_guardrails(
        guardrail_configs, text, is_input
    )

    if blocked:
        return processed_text, all_violations, blocked, block_reason

    # Then, process LLM judge for each config that has it enabled
    for config in guardrail_configs:
        if config.get("llm_judge_enabled"):
            engine = GuardrailEngine(config)
            passed, reason, _ = await engine.llm_judge(
                processed_text, is_input, generate_func
            )

            if not passed:
                blocked = True
                block_reason = reason
                all_violations.append(
                    {
                        "type": "llm_judge",
                        "guardrail_name": config.get("name", "Unknown"),
                        "reason": reason,
                    }
                )
                break

    return processed_text, all_violations, blocked, block_reason
