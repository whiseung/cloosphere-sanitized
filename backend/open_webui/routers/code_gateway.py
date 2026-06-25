"""Code Gateway — AI coding tool API proxy gateway.

Enterprise proxy for AI coding CLI tools (Claude Code, Codex CLI, Gemini CLI, Cursor).
Applies guardrails, usage tracking, and audit logging.

Developers set their tool's BASE_URL to Cloosphere and use their Cloosphere API key.
Admins can add any number of providers via the settings UI.

Supported provider types:
  - openai: OpenAI, any OpenAI-compatible endpoint, Vertex AI OpenAI
  - anthropic: Anthropic API
  - gemini: Google Gemini API, Vertex AI Gemini
  - azure_openai: Azure OpenAI Service
  - vertex_ai: Vertex AI (native Gemini API with service account auth)
"""

import base64
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from typing import Callable, Optional

import aiohttp
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from open_webui.env import AIOHTTP_CLIENT_TIMEOUT, SRC_LOG_LEVELS
from open_webui.models.usage import UsageMessageType, Usages
from open_webui.utils.access_control import has_permission
from open_webui.utils.audit_logger import AuditLogger
from open_webui.utils.auth import (
    bearer_security,
    get_admin_settings_read_access,
    get_admin_settings_write_access,
    get_current_user,
)
from open_webui.utils.crypto import mask_config_dict, resolve_config_dict
from open_webui.utils.license import require_feature
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter(dependencies=[Depends(require_feature("code_gateway"))])


####################################
#
# Client detection
#
####################################


def _detect_client(request: Request) -> str:
    """요청 헤더로 AI 코딩 클라이언트를 식별합니다.

    버전 변경에도 안정적으로 감지하기 위해 여러 신호를 복합 사용합니다:
      - User-Agent 부분 매칭 (키워드 기반)
      - 클라이언트 고유 헤더 존재 여부
      - 인증 방식 차이
    """
    ua = (request.headers.get("user-agent") or "").lower()
    headers = request.headers

    # Claude Code: UA에 "claude" 포함, 또는 anthropic-beta에 "claude-code" 포함
    if "claude" in ua and ("cli" in ua or "code" in ua):
        return "claude-code"
    anthropic_beta = (headers.get("anthropic-beta") or "").lower()
    if "claude-code" in anthropic_beta:
        return "claude-code"

    # Codex CLI: UA에 "codex" 포함, 또는 originator 헤더
    if "codex" in ua:
        return "codex-cli"
    originator = (headers.get("originator") or "").lower()
    if "codex" in originator:
        return "codex-cli"

    # Gemini CLI: UA에 "gemini" 포함, 또는 x-goog-api-client 헤더
    if "gemini" in ua:
        return "gemini-cli"
    if headers.get("x-goog-api-client"):
        return "gemini-cli"

    # Cursor: Go HTTP client (Cursor의 백엔드가 Go 기반)
    if "go-http-client" in ua:
        return "cursor"

    return "unknown"


####################################
#
# Code Gateway auth (key= query param fallback)
#
####################################


def _parse_repo_metadata(
    raw_token: str, request: Request
) -> tuple[str, Optional[dict]]:
    """토큰에서 API 키와 리포지토리 메타데이터를 분리합니다.

    지원 포맷:
      1. 토큰 내 인코딩: ``{api_key}::{base64(json)}``
      2. ``X-Cloosphere-Meta`` 헤더: base64-encoded JSON (fallback)

    Returns:
        (api_key, metadata_dict 또는 None)
    """
    api_key = raw_token
    metadata = None

    # Format 1: token::base64_metadata
    if "::" in raw_token:
        parts = raw_token.split("::", 1)
        api_key = parts[0]
        try:
            b64 = parts[1]
            b64 += "=" * (-len(b64) % 4)
            decoded = base64.urlsafe_b64decode(b64).decode("utf-8")
            metadata = json.loads(decoded)
            if not isinstance(metadata, dict):
                log.warning("[CG] Repo metadata is not a dict, ignoring")
                metadata = None
        except Exception as e:
            log.warning(f"[CG] Failed to decode repo metadata from token: {e}")

    # Format 2: X-Cloosphere-Meta header (fallback)
    if metadata is None:
        meta_header = request.headers.get("x-cloosphere-meta")
        log.info(
            f"[CG] X-Cloosphere-Meta header present: {bool(meta_header)}, value[:30]={str(meta_header)[:30] if meta_header else 'None'}"
        )
        if meta_header:
            try:
                b64 = meta_header
                b64 += "=" * (-len(b64) % 4)
                decoded = base64.urlsafe_b64decode(b64).decode("utf-8")
                metadata = json.loads(decoded)
                if not isinstance(metadata, dict):
                    metadata = None
            except Exception as e:
                log.warning(f"[CG] Failed to decode X-Cloosphere-Meta header: {e}")

    return api_key, metadata


# Cursor Hook에서 주입한 [CLOOSPHERE_REPO] 태그 패턴
# remote_urls: pipe(|) 구분 리스트 (예: url1|url2)
# remote_url: 단일 URL (하위 호환)
_CLOOSPHERE_REPO_RE = re.compile(
    r"\[CLOOSPHERE_REPO\]\s*remote_urls?=(\S*)\s*branch=(\S*)"
)


def _extract_repo_metadata_from_body(body_dict: dict) -> Optional[dict]:
    """요청 body에서 [CLOOSPHERE_REPO] 태그를 추출합니다.

    지원 API 형식:
      - Responses API (Codex CLI): input[] 배열
      - Chat Completions (Cursor, Claude Code): messages[] 배열
      - Gemini API (Gemini CLI): contents[].parts[].text
    """

    def _match_text(text: str) -> Optional[dict]:
        if not isinstance(text, str):
            return None
        m = _CLOOSPHERE_REPO_RE.search(text)
        if m:
            raw_urls = m.group(1)
            repo_urls = [u for u in raw_urls.split("|") if u] if raw_urls else []
            return {
                "repo_url": repo_urls[0] if repo_urls else "",
                "repo_urls": repo_urls,
                "branch": m.group(2),
            }
        return None

    # 1. Responses API (input[]) / Chat Completions (messages[])
    messages = body_dict.get("input") or body_dict.get("messages") or []
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                result = _match_text(content)
                if result:
                    return result
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        result = _match_text(part.get("text", ""))
                        if result:
                            return result

    # 2. Gemini API (contents[].parts[].text)
    contents = body_dict.get("contents")
    if isinstance(contents, list):
        for item in contents:
            if not isinstance(item, dict):
                continue
            for part in item.get("parts") or []:
                if isinstance(part, dict):
                    result = _match_text(part.get("text", ""))
                    if result:
                        return result

    return None


def _strip_repo_metadata_from_body(body_dict: dict) -> None:
    """요청 body에서 [CLOOSPHERE_REPO] 태그를 제거합니다.

    메타데이터 추출 후 upstream LLM에 깨끗한 메시지를 전달하기 위해 사용합니다.
    지원: input(Responses), messages(Chat Completions), contents(Gemini)
    """
    # hook_context 태그까지 함께 제거
    _hook_ctx_re = re.compile(
        r"<hook_context>\s*\[CLOOSPHERE_REPO\][^<]*</hook_context>", re.DOTALL
    )

    def _clean(text: str) -> str:
        result = _hook_ctx_re.sub("", text)
        result = _CLOOSPHERE_REPO_RE.sub("", result)
        return result.strip()

    # 1. Responses API / Chat Completions
    for key in ("input", "messages"):
        messages = body_dict.get(key)
        if not isinstance(messages, list):
            continue
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                cleaned = _clean(content)
                if cleaned != content:
                    msg["content"] = cleaned
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        cleaned = _clean(part["text"])
                        if cleaned != part["text"]:
                            part["text"] = cleaned

    # 2. Gemini API (contents[].parts[].text)
    contents = body_dict.get("contents")
    if isinstance(contents, list):
        for item in contents:
            if not isinstance(item, dict):
                continue
            for part in item.get("parts") or []:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    cleaned = _clean(part["text"])
                    if cleaned != part["text"]:
                        part["text"] = cleaned


def _get_auth_token_with_key_fallback(
    request: Request,
    auth_token: HTTPAuthorizationCredentials = Depends(bearer_security),
) -> Optional[HTTPAuthorizationCredentials]:
    """Bearer 헤더가 없으면 다른 인증 소스에서 토큰을 추출합니다.

    지원하는 fallback (우선순위 순):
      1. ``x-api-key`` 헤더 (Anthropic SDK / Claude Code CLI)
      2. ``x-goog-api-key`` 헤더 (Gemini CLI)
      3. ``key=`` 쿼리 파라미터

    토큰에 ``::`` 구분자가 있으면 리포지토리 메타데이터를 분리하여
    ``request.state.repo_metadata`` 에 저장합니다.
    """
    if auth_token is not None:
        raw = auth_token.credentials
    else:
        raw = (
            request.headers.get("x-api-key")
            or request.headers.get("x-goog-api-key")
            or request.query_params.get("key")
        )

    if not raw:
        request.state.repo_metadata = None
        return None

    api_key, metadata = _parse_repo_metadata(raw, request)
    request.state.repo_metadata = metadata

    if metadata:
        log.debug(f"[CG] Repo metadata: {metadata}")

    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=api_key)


def get_code_gateway_user(
    request: Request,
    background_tasks: BackgroundTasks,
    auth_token: HTTPAuthorizationCredentials = Depends(
        _get_auth_token_with_key_fallback
    ),
):
    """Code Gateway 전용 인증 — Bearer 헤더 + key= 쿼리 파라미터 지원."""
    user = get_current_user(request, background_tasks, auth_token)
    if user.role not in {"user", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access prohibited",
        )
    return user


# In-memory rate limiter: {user_id: [timestamp, ...]}
_rate_limit_store: dict[str, list[float]] = defaultdict(list)

# Strip these response headers when proxying
_HOP_HEADERS = frozenset({"content-length", "transfer-encoding", "content-encoding"})


####################################
#
# Pydantic models
#
####################################


class CodeGatewayConfigForm(BaseModel):
    enable: bool = False
    providers: dict[str, dict] = {}
    guardrail_ids: list[str] = []
    follow_global_guardrail: bool = False
    rate_limit: int = 0
    allowed_models: list[str] = []
    blocked_file_patterns: list[str] = []
    blocked_file_action: str = "block"  # "block" or "warn"
    blocked_repos: list[str] = []
    require_repo_metadata: bool = False
    missing_metadata_action: str = "allow"  # "allow", "warn", "block"


####################################
#
# Helper / setup script download (no auth — static content)
#
####################################

_HELPER_BASH = """\
#!/bin/bash
REPO_URL=$(git config --get remote.origin.url 2>/dev/null || echo "")
WORK_DIR=$(pwd)
META=$(printf '{"repo_url":"%s","working_dir":"%s"}' "$REPO_URL" "$WORK_DIR" | base64 | tr -d '\\n')
echo "${CLOOSPHERE_API_KEY}::${META}"
"""

_HELPER_POWERSHELL = """\
$repoUrl = & git config --get remote.origin.url 2>$null
if (-not $repoUrl) { $repoUrl = "" }
$workDir = (Get-Location).Path
$json = '{"repo_url":"' + $repoUrl + '","working_dir":"' + $workDir + '"}'
$meta = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
Write-Output "$env:CLOOSPHERE_API_KEY::$meta"
"""

_SETUP_BASH = r"""#!/bin/bash
set -e

if [ -z "$CLOOSPHERE_API_KEY" ]; then
    echo "Error: CLOOSPHERE_API_KEY is not set"
    echo "  export CLOOSPHERE_API_KEY=<your-cloosphere-api-key>"
    exit 1
fi
if [ -z "$CLOOSPHERE_GATEWAY_URL" ]; then
    echo "Error: CLOOSPHERE_GATEWAY_URL is not set"
    echo "  export CLOOSPHERE_GATEWAY_URL=<gateway-base-url>  (예: http://host:8080/api/v1/code-gateway)"
    exit 1
fi

# CLOOSPHERE_GATEWAY_URL에 provider_id가 이미 포함됨 (예: .../code-gateway/claude-sykim)
GATEWAY_BASE=$(echo "$CLOOSPHERE_GATEWAY_URL" | sed 's|/[^/]*$||')

# 1. Install helper script
curl -so ~/cloosphere-helper.sh "$GATEWAY_BASE/helper-script"
chmod +x ~/cloosphere-helper.sh
echo "[OK] Helper script: ~/cloosphere-helper.sh"

# 2. Configure ~/.claude/settings.json
mkdir -p ~/.claude
SETTINGS=~/.claude/settings.json

if command -v python3 &>/dev/null; then
    ANTHROPIC_BASE_URL="$CLOOSPHERE_GATEWAY_URL" python3 -c "
import json, os, pathlib
sf = pathlib.Path.home() / '.claude' / 'settings.json'
try:
    s = json.loads(sf.read_text()) if sf.exists() else {}
except:
    s = {}
s.setdefault('env', {})
s['env']['CLOOSPHERE_API_KEY'] = os.environ['CLOOSPHERE_API_KEY']
s['env']['ANTHROPIC_BASE_URL'] = os.environ['ANTHROPIC_BASE_URL']
s['apiKeyHelper'] = str(pathlib.Path.home() / 'cloosphere-helper.sh')
sf.write_text(json.dumps(s, indent=2) + chr(10))
"
else
    cat > "$SETTINGS" << JSONEOF
{
  "env": {
    "CLOOSPHERE_API_KEY": "$CLOOSPHERE_API_KEY",
    "ANTHROPIC_BASE_URL": "$CLOOSPHERE_GATEWAY_URL"
  },
  "apiKeyHelper": "$HOME/cloosphere-helper.sh"
}
JSONEOF
fi
echo "[OK] Settings: ~/.claude/settings.json"
echo ""
echo "Setup complete! Run 'claude' to start."
"""

_SETUP_POWERSHELL = r"""$ErrorActionPreference = "Stop"

if (-not $env:CLOOSPHERE_API_KEY) {
    Write-Error "CLOOSPHERE_API_KEY is not set. Set it with: `$env:CLOOSPHERE_API_KEY = '<key>'"
    exit 1
}
if (-not $env:CLOOSPHERE_GATEWAY_URL) {
    Write-Error "CLOOSPHERE_GATEWAY_URL is not set. Set it with: `$env:CLOOSPHERE_GATEWAY_URL = '<url>'"
    exit 1
}

# CLOOSPHERE_GATEWAY_URL에 provider_id가 이미 포함됨
$gatewayBase = $env:CLOOSPHERE_GATEWAY_URL -replace '/[^/]*$', ''

# 1. Install helper script
Invoke-WebRequest -Uri "$gatewayBase/helper-script?os=powershell" -OutFile ~/cloosphere-helper.ps1
Write-Host "[OK] Helper script: ~/cloosphere-helper.ps1"

# 2. Configure ~/.claude/settings.json
$settingsDir = Join-Path $HOME ".claude"
New-Item -ItemType Directory -Path $settingsDir -Force | Out-Null
$settingsFile = Join-Path $settingsDir "settings.json"

$settings = @{}
if (Test-Path $settingsFile) {
    try { $settings = Get-Content $settingsFile -Raw | ConvertFrom-Json -AsHashtable } catch {}
}
if (-not $settings.ContainsKey("env")) { $settings["env"] = @{} }
$settings["env"]["CLOOSPHERE_API_KEY"] = $env:CLOOSPHERE_API_KEY
$settings["env"]["ANTHROPIC_BASE_URL"] = $env:CLOOSPHERE_GATEWAY_URL
$settings["apiKeyHelper"] = "powershell -File " + (Join-Path $HOME "cloosphere-helper.ps1")

$settings | ConvertTo-Json -Depth 10 | Set-Content $settingsFile
Write-Host "[OK] Settings: $settingsFile"
Write-Host ""
Write-Host "Setup complete! Run 'claude' to start."
"""


_CURSOR_HOOK_SCRIPT = r"""#!/bin/bash
# Cloosphere Code Gateway - Cursor Hook
# 글로벌 설치: ~/.cursor/hooks/cloosphere-meta.sh
INPUT=$(cat)

EVENT=""
if command -v jq &>/dev/null; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)
fi

DIR="${CURSOR_PROJECT_DIR:-$(pwd)}"
REMOTES=$(git -C "$DIR" remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
META="[CLOOSPHERE_REPO] remote_urls=$REMOTES branch=$BRANCH"

case "$EVENT" in
  sessionStart)
    printf '{"additional_context":"%s"}\n' "$META"
    ;;
  beforeSubmitPrompt)
    printf '{"continue":true,"user_message":"%s"}\n' "$META"
    ;;
  postToolUse)
    printf '{"additional_context":"%s"}\n' "$META"
    ;;
  *)
    echo '{}'
    ;;
esac
"""

_CURSOR_HOOKS_JSON = r"""{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ],
    "beforeSubmitPrompt": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ],
    "postToolUse": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ]
  }
}
"""

_CURSOR_SETUP_BASH = r"""#!/bin/bash
set -e

# Cloosphere Code Gateway - Cursor Setup
# 글로벌 설치: ~/.cursor/hooks.json + ~/.cursor/hooks/cloosphere-meta.sh

CURSOR_DIR="$HOME/.cursor"

# 1. hooks.json
mkdir -p "$CURSOR_DIR/hooks"
if [ -f "$CURSOR_DIR/hooks.json" ]; then
    echo "[SKIP] ~/.cursor/hooks.json 이미 존재 (수동 병합 필요)"
else
    cat > "$CURSOR_DIR/hooks.json" << 'HOOKJSONEOF'
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ],
    "beforeSubmitPrompt": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ],
    "postToolUse": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ]
  }
}
HOOKJSONEOF
    echo "[OK] ~/.cursor/hooks.json"
fi

# 2. Hook script
cat > "$CURSOR_DIR/hooks/cloosphere-meta.sh" << 'HOOKSHEOF'
#!/bin/bash
INPUT=$(cat)
EVENT=""
if command -v jq &>/dev/null; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)
fi
DIR="${CURSOR_PROJECT_DIR:-$(pwd)}"
REMOTES=$(git -C "$DIR" remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
META="[CLOOSPHERE_REPO] remote_urls=$REMOTES branch=$BRANCH"
case "$EVENT" in
  sessionStart)
    printf '{"additional_context":"%s"}\n' "$META"
    ;;
  beforeSubmitPrompt)
    printf '{"continue":true,"user_message":"%s"}\n' "$META"
    ;;
  postToolUse)
    printf '{"additional_context":"%s"}\n' "$META"
    ;;
  *)
    echo '{}'
    ;;
esac
HOOKSHEOF
chmod +x "$CURSOR_DIR/hooks/cloosphere-meta.sh"
echo "[OK] ~/.cursor/hooks/cloosphere-meta.sh"

echo ""
echo "Setup complete! Cursor를 재시작하면 적용됩니다."
"""

_CURSOR_SETUP_POWERSHELL = r"""$ErrorActionPreference = "Stop"

# Cloosphere Code Gateway - Cursor Setup (PowerShell)
# 글로벌 설치: ~/.cursor/hooks.json + ~/.cursor/hooks/cloosphere-meta.sh

$cursorDir = Join-Path $HOME ".cursor"

# 1. hooks.json
New-Item -ItemType Directory -Path (Join-Path $cursorDir "hooks") -Force | Out-Null
$hooksJsonPath = Join-Path $cursorDir "hooks.json"
if (Test-Path $hooksJsonPath) {
    Write-Host "[SKIP] ~/.cursor/hooks.json 이미 존재 (수동 병합 필요)"
} else {
    @'
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ],
    "beforeSubmitPrompt": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ],
    "postToolUse": [
      {
        "command": "hooks/cloosphere-meta.sh",
        "type": "command",
        "timeout": 5
      }
    ]
  }
}
'@ | Set-Content $hooksJsonPath
    Write-Host "[OK] ~/.cursor/hooks.json"
}

# 2. Hook script
$hookScriptPath = Join-Path $cursorDir "hooks/cloosphere-meta.sh"
@'
#!/bin/bash
INPUT=$(cat)
EVENT=""
if command -v jq &>/dev/null; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)
fi
DIR="${CURSOR_PROJECT_DIR:-$(pwd)}"
REMOTES=$(git -C "$DIR" remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
META="[CLOOSPHERE_REPO] remote_urls=$REMOTES branch=$BRANCH"
case "$EVENT" in
  sessionStart)
    printf '{"additional_context":"%s"}\n' "$META"
    ;;
  beforeSubmitPrompt)
    printf '{"continue":true,"user_message":"%s"}\n' "$META"
    ;;
  postToolUse)
    printf '{"additional_context":"%s"}\n' "$META"
    ;;
  *)
    echo '{}'
    ;;
esac
'@ | Set-Content $hookScriptPath
Write-Host "[OK] ~/.cursor/hooks/cloosphere-meta.sh"

Write-Host ""
Write-Host "Setup complete! Cursor를 재시작하면 적용됩니다."
"""


_CODEX_META_SCRIPT = r"""#!/bin/bash
# Cloosphere Code Gateway - Codex CLI metadata helper
# 실행 시 CLOOSPHERE_META 환경변수에 git 정보를 base64로 설정합니다.
REMOTES=$(git remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
DIR=$(pwd)
META=$(printf '{"repo_urls":"%s","branch":"%s","working_dir":"%s"}' "$REMOTES" "$BRANCH" "$DIR" | base64 | tr -d '\n')
export CLOOSPHERE_META="$META"
"""

_CODEX_SETUP_BASH = r"""#!/bin/bash
set -e

if [ -z "$CLOOSPHERE_API_KEY" ]; then
    echo "Error: CLOOSPHERE_API_KEY is not set"
    echo "  export CLOOSPHERE_API_KEY=<your-cloosphere-api-key>"
    exit 1
fi
if [ -z "$CLOOSPHERE_GATEWAY_URL" ]; then
    echo "Error: CLOOSPHERE_GATEWAY_URL is not set"
    echo "  export CLOOSPHERE_GATEWAY_URL=<gateway-base-url>  (예: http://host:8080/api/v1/code-gateway)"
    exit 1
fi
CODEX_DIR="$HOME/.codex"
mkdir -p "$CODEX_DIR"

# 1. Install metadata helper script (source용)
cat > ~/cloosphere-codex-meta.sh << 'METAEOF'
#!/bin/bash
REMOTES=$(git remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
DIR=$(pwd)
META=$(printf '{"repo_urls":"%s","branch":"%s","working_dir":"%s"}' "$REMOTES" "$BRANCH" "$DIR" | base64 | tr -d '\n')
export CLOOSPHERE_META="$META"
METAEOF
chmod +x ~/cloosphere-codex-meta.sh
echo "[OK] Metadata script: ~/cloosphere-codex-meta.sh"

# 2. Update ~/.codex/config.toml
CONFIG="$CODEX_DIR/config.toml"
if [ -f "$CONFIG" ] && grep -q 'model_providers.cloosphere' "$CONFIG"; then
    echo "[SKIP] config.toml에 cloosphere provider 이미 존재 (수동 확인 필요)"
else
    # model, model_provider는 반드시 최상단에 위치해야 동작함
    EXISTING=""
    if [ -f "$CONFIG" ]; then
        EXISTING=$(cat "$CONFIG")
    fi
    cat > "$CONFIG" << TOMLEOF
model = "gpt-5.3-codex"
model_provider = "cloosphere"

[model_providers.cloosphere]
name = "Cloosphere Gateway"
base_url = "$CLOOSPHERE_GATEWAY_URL/v1"
env_key = "CLOOSPHERE_API_KEY"
env_http_headers = { "X-Cloosphere-Meta" = "CLOOSPHERE_META" }

$EXISTING
TOMLEOF
    echo "[OK] config.toml에 cloosphere provider 추가됨 (최상단 배치)"
fi

# 3. Add codex wrapper function + CLOOSPHERE_API_KEY to shell profile
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [ -n "$SHELL_RC" ]; then
    if ! grep -q 'cloosphere-codex-meta' "$SHELL_RC"; then
        cat >> "$SHELL_RC" << RCEOF

# Cloosphere Code Gateway - Codex metadata auto-injection
export CLOOSPHERE_API_KEY="$CLOOSPHERE_API_KEY"
codex() { source ~/cloosphere-codex-meta.sh; command codex "\$@"; }
RCEOF
        echo "[OK] $SHELL_RC에 codex wrapper 추가됨"
    else
        echo "[SKIP] $SHELL_RC에 이미 설정 존재"
    fi
fi

# 4. Apply to current shell immediately
export CLOOSPHERE_API_KEY="$CLOOSPHERE_API_KEY"
source ~/cloosphere-codex-meta.sh
codex() { source ~/cloosphere-codex-meta.sh; command codex "$@"; }

echo ""
echo "Setup complete! 바로 codex 실행 가능합니다."
"""

_CODEX_SETUP_POWERSHELL = r"""$ErrorActionPreference = "Stop"

if (-not $env:CLOOSPHERE_API_KEY) {
    Write-Error "CLOOSPHERE_API_KEY is not set. Set it with: `$env:CLOOSPHERE_API_KEY = '<key>'"
    exit 1
}
if (-not $env:CLOOSPHERE_GATEWAY_URL) {
    Write-Error "CLOOSPHERE_GATEWAY_URL is not set. Set it with: `$env:CLOOSPHERE_GATEWAY_URL = '<url>'"
    exit 1
}
$codexDir = Join-Path $HOME ".codex"
New-Item -ItemType Directory -Path $codexDir -Force | Out-Null

# 1. Install metadata helper script
$metaScript = @'
$remotes = & git remote -v 2>$null | Where-Object { $_ -match '\(fetch\)' } | ForEach-Object { ($_ -split '\s+')[1] } | Sort-Object -Unique
$remotesStr = ($remotes -join '|')
$branch = & git rev-parse --abbrev-ref HEAD 2>$null
if (-not $branch) { $branch = "" }
$dir = (Get-Location).Path
$json = '{"repo_urls":"' + $remotesStr + '","branch":"' + $branch + '","working_dir":"' + $dir + '"}'
$meta = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
$env:CLOOSPHERE_META = $meta
'@
$metaScriptPath = Join-Path $HOME "cloosphere-codex-meta.ps1"
Set-Content -Path $metaScriptPath -Value $metaScript
Write-Host "[OK] Metadata script: $metaScriptPath"

# 2. Update config.toml
$configPath = Join-Path $codexDir "config.toml"
$configContent = if (Test-Path $configPath) { Get-Content $configPath -Raw } else { "" }
if ($configContent -match 'model_providers\.cloosphere') {
    Write-Host "[SKIP] config.toml에 cloosphere provider 이미 존재"
} else {
    $providerConfig = @"

[model_providers.cloosphere]
name = "Cloosphere Gateway"
base_url = "$env:CLOOSPHERE_GATEWAY_URL/v1"
env_key = "CLOOSPHERE_API_KEY"
env_http_headers = { "X-Cloosphere-Meta" = "CLOOSPHERE_META" }
"@
    Add-Content -Path $configPath -Value $providerConfig
    Write-Host "[OK] config.toml에 cloosphere provider 추가됨"
}

# 3. Add PowerShell profile wrapper
$profilePath = $PROFILE
$profileDir = Split-Path $profilePath
if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }
$profileContent = if (Test-Path $profilePath) { Get-Content $profilePath -Raw } else { "" }
if ($profileContent -notmatch 'cloosphere-codex-meta') {
    $wrapper = @"

# Cloosphere Code Gateway - Codex metadata auto-injection
`$env:CLOOSPHERE_API_KEY = "$env:CLOOSPHERE_API_KEY"
function codex { . ~/cloosphere-codex-meta.ps1; & (Get-Command codex -CommandType Application).Source @args }
"@
    Add-Content -Path $profilePath -Value $wrapper
    Write-Host "[OK] PowerShell profile에 codex wrapper 추가됨"
} else {
    Write-Host "[SKIP] PowerShell profile에 이미 설정 존재"
}

Write-Host ""
Write-Host "Setup complete! 새 터미널을 열면 codex 실행 시 자동으로 git 메타데이터가 수집됩니다."
"""


@router.get("/codex-setup-script")
async def get_codex_setup_script(os: str = "bash"):
    """Codex CLI 셋업 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _CODEX_SETUP_POWERSHELL
    else:
        content = _CODEX_SETUP_BASH
    return PlainTextResponse(content=content)


@router.get("/codex-meta-script")
async def get_codex_meta_script():
    """Codex CLI metadata 스크립트 단독 다운로드 (인증 불필요)."""
    return PlainTextResponse(
        content=_CODEX_META_SCRIPT,
        headers={
            "Content-Disposition": 'attachment; filename="cloosphere-codex-meta.sh"'
        },
    )


_GEMINI_HOOK_SCRIPT = r"""#!/bin/bash
# Cloosphere Code Gateway - Gemini CLI Hook
# 글로벌 설치: ~/.gemini/hooks/cloosphere-meta.sh
# stdout에 JSON만 출력해야 합니다 (디버그는 stderr로)
INPUT=$(cat)

EVENT=""
if command -v jq &>/dev/null; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)
fi

DIR="${GEMINI_PROJECT_DIR:-${GEMINI_CWD:-$(pwd)}}"
REMOTES=$(git -C "$DIR" remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
META="[CLOOSPHERE_REPO] remote_urls=$REMOTES branch=$BRANCH"

case "$EVENT" in
  SessionStart)
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$META"
    ;;
  BeforeAgent)
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$META"
    ;;
  *)
    echo '{}'
    ;;
esac
"""

_GEMINI_SETUP_BASH = r"""#!/bin/bash
set -e

if [ -z "$CLOOSPHERE_API_KEY" ]; then
    echo "Error: CLOOSPHERE_API_KEY is not set"
    echo "  export CLOOSPHERE_API_KEY=<your-cloosphere-api-key>"
    exit 1
fi
if [ -z "$CLOOSPHERE_GATEWAY_URL" ]; then
    echo "Error: CLOOSPHERE_GATEWAY_URL is not set"
    echo "  export CLOOSPHERE_GATEWAY_URL=<gateway-url>  (예: http://host:8080/api/v1/code-gateway/gemini)"
    exit 1
fi

GEMINI_DIR="$HOME/.gemini"
mkdir -p "$GEMINI_DIR/hooks"

# 1. Install hook script
cat > "$GEMINI_DIR/hooks/cloosphere-meta.sh" << 'HOOKEOF'
#!/bin/bash
INPUT=$(cat)
EVENT=""
if command -v jq &>/dev/null; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)
fi
DIR="${GEMINI_PROJECT_DIR:-${GEMINI_CWD:-$(pwd)}}"
REMOTES=$(git -C "$DIR" remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
META="[CLOOSPHERE_REPO] remote_urls=$REMOTES branch=$BRANCH"
case "$EVENT" in
  SessionStart)
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$META"
    ;;
  BeforeAgent)
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$META"
    ;;
  *)
    echo '{}'
    ;;
esac
HOOKEOF
chmod +x "$GEMINI_DIR/hooks/cloosphere-meta.sh"
echo "[OK] Hook script: ~/.gemini/hooks/cloosphere-meta.sh"

# 2. Update ~/.gemini/settings.json
SETTINGS="$GEMINI_DIR/settings.json"
if command -v python3 &>/dev/null; then
    python3 -c "
import json, pathlib
sf = pathlib.Path.home() / '.gemini' / 'settings.json'
try:
    s = json.loads(sf.read_text()) if sf.exists() else {}
except:
    s = {}
s.setdefault('hooks', {})
hook_cmd = str(pathlib.Path.home() / '.gemini' / 'hooks' / 'cloosphere-meta.sh')
hook_entry = [{'hooks': [{'type': 'command', 'command': hook_cmd, 'name': 'Cloosphere Metadata', 'timeout': 5000}]}]
s['hooks']['SessionStart'] = hook_entry
s['hooks']['BeforeAgent'] = hook_entry
sf.write_text(json.dumps(s, indent=2) + chr(10))
"
    echo "[OK] Settings: ~/.gemini/settings.json (hooks 등록)"
else
    if [ -f "$SETTINGS" ] && grep -q 'cloosphere-meta' "$SETTINGS"; then
        echo "[SKIP] settings.json에 이미 hook 존재"
    else
        cat > "$SETTINGS" << JSONEOF
{
  "hooks": {
    "SessionStart": [{"hooks": [{"type": "command", "command": "$HOME/.gemini/hooks/cloosphere-meta.sh", "name": "Cloosphere Metadata", "timeout": 5000}]}],
    "BeforeAgent": [{"hooks": [{"type": "command", "command": "$HOME/.gemini/hooks/cloosphere-meta.sh", "name": "Cloosphere Metadata", "timeout": 5000}]}]
  }
}
JSONEOF
        echo "[OK] Settings: ~/.gemini/settings.json (hooks 등록)"
    fi
fi

# 3. Set GEMINI_API_KEY + GOOGLE_GEMINI_BASE_URL in shell profile
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [ -n "$SHELL_RC" ]; then
    if ! grep -q 'GEMINI_API_KEY.*CLOOSPHERE' "$SHELL_RC" && ! grep -q 'GOOGLE_GEMINI_BASE_URL' "$SHELL_RC"; then
        cat >> "$SHELL_RC" << RCEOF

# Cloosphere Code Gateway - Gemini CLI
export GEMINI_API_KEY="$CLOOSPHERE_API_KEY"
export GOOGLE_GEMINI_BASE_URL="$CLOOSPHERE_GATEWAY_URL"
RCEOF
        echo "[OK] $SHELL_RC에 환경변수 추가됨"
    else
        echo "[SKIP] $SHELL_RC에 이미 설정 존재"
    fi
fi

# 4. Apply to current shell
export GEMINI_API_KEY="$CLOOSPHERE_API_KEY"
export GOOGLE_GEMINI_BASE_URL="$CLOOSPHERE_GATEWAY_URL"

echo ""
echo "Setup complete! gemini 명령으로 시작하세요."
"""


_GEMINI_SETUP_POWERSHELL = r"""$ErrorActionPreference = "Stop"

if (-not $env:CLOOSPHERE_API_KEY) {
    Write-Error "CLOOSPHERE_API_KEY is not set. Set it with: `$env:CLOOSPHERE_API_KEY = '<key>'"
    exit 1
}
if (-not $env:CLOOSPHERE_GATEWAY_URL) {
    Write-Error "CLOOSPHERE_GATEWAY_URL is not set. Set it with: `$env:CLOOSPHERE_GATEWAY_URL = '<url>'"
    exit 1
}

$geminiDir = Join-Path $HOME ".gemini"
New-Item -ItemType Directory -Path (Join-Path $geminiDir "hooks") -Force | Out-Null

# 1. Install hook script
$hookScript = @'
#!/bin/bash
INPUT=$(cat)
EVENT=""
if command -v jq &>/dev/null; then
  EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // empty')
else
  EVENT=$(echo "$INPUT" | grep -o '"hook_event_name":"[^"]*"' | cut -d'"' -f4)
fi
DIR="${GEMINI_PROJECT_DIR:-${GEMINI_CWD:-$(pwd)}}"
REMOTES=$(git -C "$DIR" remote -v 2>/dev/null | awk '/(fetch)/{print $2}' | sort -u | paste -sd'|' -)
REMOTES="${REMOTES:-}"
BRANCH=$(git -C "$DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
META="[CLOOSPHERE_REPO] remote_urls=$REMOTES branch=$BRANCH"
case "$EVENT" in
  SessionStart)
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$META"
    ;;
  BeforeAgent)
    printf '{"hookSpecificOutput":{"additionalContext":"%s"}}\n' "$META"
    ;;
  *)
    echo '{}'
    ;;
esac
'@
$hookPath = Join-Path $geminiDir "hooks/cloosphere-meta.sh"
Set-Content -Path $hookPath -Value $hookScript -NoNewline
Write-Host "[OK] Hook script: $hookPath"

# 2. Update settings.json
$settingsPath = Join-Path $geminiDir "settings.json"
$s = @{}
if (Test-Path $settingsPath) {
    try { $s = Get-Content $settingsPath -Raw | ConvertFrom-Json -AsHashtable } catch {}
}
if (-not $s.ContainsKey("hooks")) { $s["hooks"] = @{} }

$hookEntry = @(@{
    hooks = @(@{
        type = "command"
        command = $hookPath
        name = "Cloosphere Metadata"
        timeout = 5000
    })
})
$s["hooks"]["SessionStart"] = $hookEntry
$s["hooks"]["BeforeAgent"] = $hookEntry
$s | ConvertTo-Json -Depth 10 | Set-Content $settingsPath
Write-Host "[OK] Settings: $settingsPath (hooks 등록)"

# 3. Set environment variables
$env:GEMINI_API_KEY = $env:CLOOSPHERE_API_KEY
$env:GOOGLE_GEMINI_BASE_URL = $env:CLOOSPHERE_GATEWAY_URL

Write-Host ""
Write-Host "Setup complete! gemini 명령으로 시작하세요."
"""


@router.get("/gemini-setup-script")
async def get_gemini_setup_script(os: str = "bash"):
    """Gemini CLI 셋업 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _GEMINI_SETUP_POWERSHELL
    else:
        content = _GEMINI_SETUP_BASH
    return PlainTextResponse(content=content)


@router.get("/gemini-hook-script")
async def get_gemini_hook_script():
    """Gemini CLI Hook 스크립트 단독 다운로드 (인증 불필요)."""
    return PlainTextResponse(
        content=_GEMINI_HOOK_SCRIPT,
        headers={"Content-Disposition": 'attachment; filename="cloosphere-meta.sh"'},
    )


####################################
#
# Uninstall scripts
#
####################################

_CURSOR_UNINSTALL_BASH = r"""#!/bin/bash
echo "=== Cloosphere Cursor Hook 제거 ==="

# 1. Remove hook script
if [ -f "$HOME/.cursor/hooks/cloosphere-meta.sh" ]; then
    rm -f "$HOME/.cursor/hooks/cloosphere-meta.sh"
    echo "[OK] ~/.cursor/hooks/cloosphere-meta.sh 삭제"
else
    echo "[SKIP] Hook 스크립트 없음"
fi

# 2. Remove hooks.json entries (cloosphere-meta 관련)
HOOKS_JSON="$HOME/.cursor/hooks.json"
if [ -f "$HOOKS_JSON" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json, pathlib
hf = pathlib.Path.home() / '.cursor' / 'hooks.json'
try:
    h = json.loads(hf.read_text())
except:
    exit(0)
changed = False
if 'hooks' in h:
    for event in list(h['hooks'].keys()):
        entries = h['hooks'][event]
        if isinstance(entries, list):
            filtered = [e for e in entries if not any('cloosphere' in hook.get('command','') for hook in e.get('hooks',[]))]
            if len(filtered) != len(entries):
                h['hooks'][event] = filtered
                changed = True
            if not h['hooks'][event]:
                del h['hooks'][event]
if changed:
    hf.write_text(json.dumps(h, indent=2) + chr(10))
    print('[OK] hooks.json에서 cloosphere 항목 제거')
else:
    print('[SKIP] hooks.json에 cloosphere 항목 없음')
"
else
    echo "[SKIP] hooks.json 처리 불가 (python3 필요)"
fi

echo ""
echo "제거 완료! Cursor를 재시작하면 적용됩니다."
"""

_CURSOR_UNINSTALL_POWERSHELL = r"""$ErrorActionPreference = "Stop"
Write-Host "=== Cloosphere Cursor Hook 제거 ==="

# 1. Remove hook script
$hookPath = Join-Path $HOME ".cursor/hooks/cloosphere-meta.sh"
if (Test-Path $hookPath) {
    Remove-Item $hookPath -Force
    Write-Host "[OK] ~/.cursor/hooks/cloosphere-meta.sh 삭제"
} else {
    Write-Host "[SKIP] Hook 스크립트 없음"
}

# 2. Remove hooks.json entries
$hooksJson = Join-Path $HOME ".cursor/hooks.json"
if (Test-Path $hooksJson) {
    $content = Get-Content $hooksJson -Raw | ConvertFrom-Json -AsHashtable
    $changed = $false
    if ($content.ContainsKey("hooks")) {
        foreach ($event in @($content["hooks"].Keys)) {
            $entries = $content["hooks"][$event]
            if ($entries -is [array]) {
                $filtered = @($entries | Where-Object {
                    $dominated = $false
                    foreach ($h in $_.hooks) {
                        if ($h.command -match "cloosphere") { $dominated = $true }
                    }
                    -not $dominated
                })
                if ($filtered.Count -ne $entries.Count) {
                    $content["hooks"][$event] = $filtered
                    $changed = $true
                }
            }
        }
    }
    if ($changed) {
        $content | ConvertTo-Json -Depth 10 | Set-Content $hooksJson
        Write-Host "[OK] hooks.json에서 cloosphere 항목 제거"
    } else {
        Write-Host "[SKIP] hooks.json에 cloosphere 항목 없음"
    }
} else {
    Write-Host "[SKIP] hooks.json 없음"
}

Write-Host ""
Write-Host "제거 완료! Cursor를 재시작하면 적용됩니다."
"""

_CODEX_UNINSTALL_BASH = r"""#!/bin/bash
echo "=== Cloosphere Codex CLI 설정 제거 ==="

# 1. Remove metadata script
if [ -f "$HOME/cloosphere-codex-meta.sh" ]; then
    rm -f "$HOME/cloosphere-codex-meta.sh"
    echo "[OK] ~/cloosphere-codex-meta.sh 삭제"
else
    echo "[SKIP] 메타데이터 스크립트 없음"
fi

# 2. Remove cloosphere provider from config.toml
CONFIG="$HOME/.codex/config.toml"
if [ -f "$CONFIG" ] && command -v python3 &>/dev/null; then
    python3 -c "
import pathlib, re
cf = pathlib.Path.home() / '.codex' / 'config.toml'
text = cf.read_text()
# Remove model_provider = \"cloosphere\" and model = ... lines
text = re.sub(r'^model_provider\s*=\s*\"cloosphere\"\s*\n?', '', text, flags=re.MULTILINE)
text = re.sub(r'^model\s*=\s*\"[^\"]*\"\s*\n?', '', text, count=1, flags=re.MULTILINE)
# Remove [model_providers.cloosphere] section
text = re.sub(r'\[model_providers\.cloosphere\][^\[]*', '', text, flags=re.DOTALL)
cf.write_text(text.strip() + chr(10))
print('[OK] config.toml에서 cloosphere 설정 제거')
"
else
    echo "[SKIP] config.toml 처리 불가"
fi

# 3. Remove codex wrapper and env vars from shell profile
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then SHELL_RC="$HOME/.zshrc"; elif [ -f "$HOME/.bashrc" ]; then SHELL_RC="$HOME/.bashrc"; fi
if [ -n "$SHELL_RC" ]; then
    if grep -q 'cloosphere-codex-meta\|CLOOSPHERE_API_KEY' "$SHELL_RC"; then
        sed -i '/cloosphere-codex-meta/d;/CLOOSPHERE_API_KEY/d;/# Cloosphere Code Gateway - Codex/d' "$SHELL_RC"
        echo "[OK] $SHELL_RC에서 cloosphere 관련 설정 제거"
    else
        echo "[SKIP] $SHELL_RC에 cloosphere 설정 없음"
    fi
fi

# 4. Unset from current shell
unset CLOOSPHERE_API_KEY CLOOSPHERE_META
unset -f codex 2>/dev/null

echo ""
echo "제거 완료! 새 터미널을 열면 적용됩니다."
"""

_CODEX_UNINSTALL_POWERSHELL = r"""$ErrorActionPreference = "Stop"
Write-Host "=== Cloosphere Codex CLI 설정 제거 ==="

# 1. Remove metadata script
$metaPath = Join-Path $HOME "cloosphere-codex-meta.ps1"
if (Test-Path $metaPath) { Remove-Item $metaPath -Force; Write-Host "[OK] 메타데이터 스크립트 삭제" }
else { Write-Host "[SKIP] 메타데이터 스크립트 없음" }

# 2. Remove from config.toml
$configPath = Join-Path $HOME ".codex/config.toml"
if (Test-Path $configPath) {
    $text = Get-Content $configPath -Raw
    $text = $text -replace '(?m)^model_provider\s*=\s*"cloosphere"\s*\n?', ''
    $text = $text -replace '(?s)\[model_providers\.cloosphere\][^\[]*', ''
    Set-Content $configPath -Value $text.Trim()
    Write-Host "[OK] config.toml에서 cloosphere 설정 제거"
}

# 3. Remove from PowerShell profile
if (Test-Path $PROFILE) {
    $profileText = Get-Content $PROFILE -Raw
    if ($profileText -match 'cloosphere') {
        $profileText = $profileText -replace '(?m)^.*cloosphere.*$\n?', ''
        Set-Content $PROFILE -Value $profileText.Trim()
        Write-Host "[OK] PowerShell profile에서 cloosphere 설정 제거"
    }
}

Write-Host "제거 완료!"
"""

_CLAUDE_UNINSTALL_BASH = r"""#!/bin/bash
echo "=== Cloosphere Claude Code 설정 제거 ==="

# 1. Remove helper script
if [ -f "$HOME/cloosphere-helper.sh" ]; then
    rm -f "$HOME/cloosphere-helper.sh"
    echo "[OK] ~/cloosphere-helper.sh 삭제"
else
    echo "[SKIP] 헬퍼 스크립트 없음"
fi

# 2. Remove from ~/.claude/settings.json
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json, pathlib
sf = pathlib.Path.home() / '.claude' / 'settings.json'
try:
    s = json.loads(sf.read_text())
except:
    exit(0)
changed = False
env = s.get('env', {})
for k in ['CLOOSPHERE_API_KEY', 'ANTHROPIC_BASE_URL', 'ANTHROPIC_API_KEY']:
    if k in env:
        del env[k]
        changed = True
if 'apiKeyHelper' in s:
    del s['apiKeyHelper']
    changed = True
if changed:
    sf.write_text(json.dumps(s, indent=2) + chr(10))
    print('[OK] settings.json에서 cloosphere 설정 제거')
else:
    print('[SKIP] settings.json에 cloosphere 설정 없음')
"
fi

echo ""
echo "제거 완료! claude를 재시작하면 적용됩니다."
"""

_CLAUDE_UNINSTALL_POWERSHELL = r"""$ErrorActionPreference = "Stop"
Write-Host "=== Cloosphere Claude Code 설정 제거 ==="

# 1. Remove helper script
$helperPath = Join-Path $HOME "cloosphere-helper.ps1"
if (Test-Path $helperPath) { Remove-Item $helperPath -Force; Write-Host "[OK] 헬퍼 스크립트 삭제" }
else { Write-Host "[SKIP] 헬퍼 스크립트 없음" }

# 2. Remove from settings.json
$settingsPath = Join-Path $HOME ".claude/settings.json"
if (Test-Path $settingsPath) {
    $s = Get-Content $settingsPath -Raw | ConvertFrom-Json -AsHashtable
    $changed = $false
    foreach ($k in @("CLOOSPHERE_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY")) {
        if ($s.ContainsKey("env") -and $s["env"].ContainsKey($k)) { $s["env"].Remove($k); $changed = $true }
    }
    if ($s.ContainsKey("apiKeyHelper")) { $s.Remove("apiKeyHelper"); $changed = $true }
    if ($changed) {
        $s | ConvertTo-Json -Depth 10 | Set-Content $settingsPath
        Write-Host "[OK] settings.json에서 cloosphere 설정 제거"
    }
}

Write-Host "제거 완료!"
"""

_GEMINI_UNINSTALL_BASH = r"""#!/bin/bash
echo "=== Cloosphere Gemini CLI 설정 제거 ==="

# 1. Remove hook script
if [ -f "$HOME/.gemini/hooks/cloosphere-meta.sh" ]; then
    rm -f "$HOME/.gemini/hooks/cloosphere-meta.sh"
    echo "[OK] ~/.gemini/hooks/cloosphere-meta.sh 삭제"
else
    echo "[SKIP] Hook 스크립트 없음"
fi

# 2. Remove hooks from settings.json
SETTINGS="$HOME/.gemini/settings.json"
if [ -f "$SETTINGS" ] && command -v python3 &>/dev/null; then
    python3 -c "
import json, pathlib
sf = pathlib.Path.home() / '.gemini' / 'settings.json'
try:
    s = json.loads(sf.read_text())
except:
    exit(0)
changed = False
hooks = s.get('hooks', {})
for event in list(hooks.keys()):
    entries = hooks[event]
    if isinstance(entries, list):
        filtered = [e for e in entries if not any('cloosphere' in h.get('command','') for h in e.get('hooks',[]))]
        if len(filtered) != len(entries):
            hooks[event] = filtered
            changed = True
        if not hooks[event]:
            del hooks[event]
if changed:
    sf.write_text(json.dumps(s, indent=2) + chr(10))
    print('[OK] settings.json에서 cloosphere hook 제거')
else:
    print('[SKIP] settings.json에 cloosphere hook 없음')
"
fi

# 3. Remove env vars from shell profile
SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then SHELL_RC="$HOME/.zshrc"; elif [ -f "$HOME/.bashrc" ]; then SHELL_RC="$HOME/.bashrc"; fi
if [ -n "$SHELL_RC" ]; then
    if grep -q 'GEMINI_API_KEY.*CLOOSPHERE\|GOOGLE_GEMINI_BASE_URL\|# Cloosphere Code Gateway - Gemini' "$SHELL_RC"; then
        sed -i '/# Cloosphere Code Gateway - Gemini/d;/GEMINI_API_KEY/d;/GOOGLE_GEMINI_BASE_URL/d' "$SHELL_RC"
        echo "[OK] $SHELL_RC에서 cloosphere 관련 설정 제거"
    else
        echo "[SKIP] $SHELL_RC에 cloosphere 설정 없음"
    fi
fi

# 4. Unset from current shell
unset GEMINI_API_KEY GOOGLE_GEMINI_BASE_URL

echo ""
echo "제거 완료! gemini를 재시작하면 적용됩니다."
"""


@router.get("/cursor-uninstall-script")
async def get_cursor_uninstall_script(os: str = "bash"):
    """Cursor Hook 제거 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _CURSOR_UNINSTALL_POWERSHELL
    else:
        content = _CURSOR_UNINSTALL_BASH
    return PlainTextResponse(content=content)


@router.get("/codex-uninstall-script")
async def get_codex_uninstall_script(os: str = "bash"):
    """Codex CLI 제거 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _CODEX_UNINSTALL_POWERSHELL
    else:
        content = _CODEX_UNINSTALL_BASH
    return PlainTextResponse(content=content)


@router.get("/claude-uninstall-script")
async def get_claude_uninstall_script(os: str = "bash"):
    """Claude Code 제거 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _CLAUDE_UNINSTALL_POWERSHELL
    else:
        content = _CLAUDE_UNINSTALL_BASH
    return PlainTextResponse(content=content)


_GEMINI_UNINSTALL_POWERSHELL = r"""$ErrorActionPreference = "Stop"
Write-Host "=== Cloosphere Gemini CLI 설정 제거 ==="

# 1. Remove hook script
$hookPath = Join-Path $HOME ".gemini/hooks/cloosphere-meta.sh"
if (Test-Path $hookPath) {
    Remove-Item $hookPath -Force
    Write-Host "[OK] Hook 스크립트 삭제"
} else {
    Write-Host "[SKIP] Hook 스크립트 없음"
}

# 2. Remove hooks from settings.json
$settingsPath = Join-Path $HOME ".gemini/settings.json"
if (Test-Path $settingsPath) {
    $s = Get-Content $settingsPath -Raw | ConvertFrom-Json -AsHashtable
    $changed = $false
    if ($s.ContainsKey("hooks")) {
        foreach ($event in @($s["hooks"].Keys)) {
            $entries = $s["hooks"][$event]
            if ($entries -is [array]) {
                $filtered = @($entries | Where-Object {
                    $dominated = $false
                    foreach ($h in $_.hooks) {
                        if ($h.command -match "cloosphere") { $dominated = $true }
                    }
                    -not $dominated
                })
                if ($filtered.Count -ne $entries.Count) {
                    $s["hooks"][$event] = $filtered
                    $changed = $true
                }
                if ($s["hooks"][$event].Count -eq 0) {
                    $s["hooks"].Remove($event)
                }
            }
        }
    }
    if ($changed) {
        $s | ConvertTo-Json -Depth 10 | Set-Content $settingsPath
        Write-Host "[OK] settings.json에서 cloosphere hook 제거"
    } else {
        Write-Host "[SKIP] settings.json에 cloosphere hook 없음"
    }
}

# 3. Unset env vars
Remove-Item Env:GEMINI_API_KEY -ErrorAction SilentlyContinue
Remove-Item Env:GOOGLE_GEMINI_BASE_URL -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "제거 완료!"
"""


@router.get("/gemini-uninstall-script")
async def get_gemini_uninstall_script(os: str = "bash"):
    """Gemini CLI 제거 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _GEMINI_UNINSTALL_POWERSHELL
    else:
        content = _GEMINI_UNINSTALL_BASH
    return PlainTextResponse(content=content)


@router.get("/cursor-setup-script")
async def get_cursor_setup_script(os: str = "bash"):
    """Cursor Hook 셋업 스크립트 다운로드 (인증 불필요)."""
    if os == "powershell":
        content = _CURSOR_SETUP_POWERSHELL
    else:
        content = _CURSOR_SETUP_BASH
    return PlainTextResponse(content=content)


@router.get("/cursor-hook-script")
async def get_cursor_hook_script():
    """Cursor Hook 스크립트 단독 다운로드 (인증 불필요)."""
    return PlainTextResponse(
        content=_CURSOR_HOOK_SCRIPT,
        headers={"Content-Disposition": 'attachment; filename="cloosphere-meta.sh"'},
    )


@router.get("/helper-script")
async def get_helper_script(os: str = "bash"):
    """헬퍼 스크립트 다운로드 (인증 불필요 — 정적 콘텐츠)."""
    if os == "powershell":
        content, filename = _HELPER_POWERSHELL, "cloosphere-helper.ps1"
    else:
        content, filename = _HELPER_BASH, "cloosphere-helper.sh"
    return PlainTextResponse(
        content=content,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/setup-script")
async def get_setup_script(os: str = "bash"):
    """셋업 스크립트 다운로드 — 헬퍼 설치 + settings.json 구성."""
    if os == "powershell":
        content = _SETUP_POWERSHELL
    else:
        content = _SETUP_BASH
    return PlainTextResponse(content=content)


####################################
#
# Config endpoints (admin)
#
####################################


@router.get("/config")
async def get_code_gateway_config(
    request: Request,
    user=Depends(get_admin_settings_read_access),
):
    gids = request.app.state.config.CODE_GATEWAY_GUARDRAIL_IDS
    log.info(f"[CG] Config GET: guardrail_ids={gids}")
    return mask_config_dict(
        {
            "enable": request.app.state.config.ENABLE_CODE_GATEWAY,
            "providers": request.app.state.config.CODE_GATEWAY_PROVIDERS,
            "guardrail_ids": gids,
            "follow_global_guardrail": request.app.state.config.CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL,
            "rate_limit": request.app.state.config.CODE_GATEWAY_RATE_LIMIT,
            "allowed_models": request.app.state.config.CODE_GATEWAY_ALLOWED_MODELS,
            "blocked_file_patterns": request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_PATTERNS,
            "blocked_file_action": request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_ACTION,
            "blocked_repos": request.app.state.config.CODE_GATEWAY_BLOCKED_REPOS,
            "require_repo_metadata": request.app.state.config.CODE_GATEWAY_REQUIRE_REPO_METADATA,
            "missing_metadata_action": request.app.state.config.CODE_GATEWAY_MISSING_METADATA_ACTION,
        }
    )


@router.post("/config")
async def set_code_gateway_config(
    request: Request,
    form_data: CodeGatewayConfigForm,
    user=Depends(get_admin_settings_write_access),
):
    before = {
        "enable": request.app.state.config.ENABLE_CODE_GATEWAY,
        "providers": request.app.state.config.CODE_GATEWAY_PROVIDERS,
        "guardrail_ids": request.app.state.config.CODE_GATEWAY_GUARDRAIL_IDS,
        "follow_global_guardrail": request.app.state.config.CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL,
        "rate_limit": request.app.state.config.CODE_GATEWAY_RATE_LIMIT,
        "allowed_models": request.app.state.config.CODE_GATEWAY_ALLOWED_MODELS,
        "blocked_file_patterns": request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_PATTERNS,
        "blocked_file_action": request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_ACTION,
        "blocked_repos": request.app.state.config.CODE_GATEWAY_BLOCKED_REPOS,
        "require_repo_metadata": request.app.state.config.CODE_GATEWAY_REQUIRE_REPO_METADATA,
        "missing_metadata_action": request.app.state.config.CODE_GATEWAY_MISSING_METADATA_ACTION,
    }

    log.info(
        f"[CG] Config save: guardrail_ids={form_data.guardrail_ids}, "
        f"enable={form_data.enable}"
    )
    request.app.state.config.ENABLE_CODE_GATEWAY = form_data.enable
    # Resolve masked sensitive values (api_key, service_account_key) in providers
    resolved_providers = {}
    current_providers = request.app.state.config.CODE_GATEWAY_PROVIDERS or {}
    for pid, pconf in form_data.providers.items():
        cur_pconf = current_providers.get(pid, {})
        resolved_providers[pid] = resolve_config_dict(pconf, cur_pconf)
    request.app.state.config.CODE_GATEWAY_PROVIDERS = resolved_providers
    request.app.state.config.CODE_GATEWAY_GUARDRAIL_IDS = form_data.guardrail_ids
    request.app.state.config.CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL = (
        form_data.follow_global_guardrail
    )
    request.app.state.config.CODE_GATEWAY_RATE_LIMIT = form_data.rate_limit
    request.app.state.config.CODE_GATEWAY_ALLOWED_MODELS = form_data.allowed_models
    request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_PATTERNS = (
        form_data.blocked_file_patterns
    )
    request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_ACTION = (
        form_data.blocked_file_action
    )
    request.app.state.config.CODE_GATEWAY_BLOCKED_REPOS = form_data.blocked_repos
    request.app.state.config.CODE_GATEWAY_REQUIRE_REPO_METADATA = (
        form_data.require_repo_metadata
    )
    request.app.state.config.CODE_GATEWAY_MISSING_METADATA_ACTION = (
        form_data.missing_metadata_action
    )

    after = {
        "enable": request.app.state.config.ENABLE_CODE_GATEWAY,
        "providers": request.app.state.config.CODE_GATEWAY_PROVIDERS,
        "guardrail_ids": request.app.state.config.CODE_GATEWAY_GUARDRAIL_IDS,
        "follow_global_guardrail": request.app.state.config.CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL,
        "rate_limit": request.app.state.config.CODE_GATEWAY_RATE_LIMIT,
        "allowed_models": request.app.state.config.CODE_GATEWAY_ALLOWED_MODELS,
        "blocked_file_patterns": request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_PATTERNS,
        "blocked_file_action": request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_ACTION,
        "blocked_repos": request.app.state.config.CODE_GATEWAY_BLOCKED_REPOS,
        "require_repo_metadata": request.app.state.config.CODE_GATEWAY_REQUIRE_REPO_METADATA,
        "missing_metadata_action": request.app.state.config.CODE_GATEWAY_MISSING_METADATA_ACTION,
    }

    AuditLogger.log_settings_change(
        "code_gateway", before_data=before, after_data=after
    )

    return mask_config_dict(after)


####################################
#
# Usage log endpoints (admin)
#
####################################


@router.get("/usage-logs")
async def get_code_gateway_usage_logs(
    page: int = 1,
    limit: int = 50,
    user_id: Optional[str] = None,
    model_id: Optional[str] = None,
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    user=Depends(get_admin_settings_read_access),
):
    return Usages.get_code_gateway_logs(
        page=page,
        limit=limit,
        user_id=user_id,
        model_id=model_id,
        from_date=from_date,
        to_date=to_date,
    )


@router.get("/usage-logs/stats")
async def get_code_gateway_usage_stats(
    from_date: Optional[int] = None,
    to_date: Optional[int] = None,
    user=Depends(get_admin_settings_read_access),
):
    return Usages.get_code_gateway_stats(from_date=from_date, to_date=to_date)


@router.get("/usage-logs/filters/models")
async def get_code_gateway_filter_models(
    user=Depends(get_admin_settings_read_access),
):
    return Usages.get_code_gateway_filter_models()


@router.get("/usage-logs/filters/users")
async def get_code_gateway_filter_users(
    user=Depends(get_admin_settings_read_access),
):
    return Usages.get_code_gateway_filter_users()


####################################
#
# Dynamic proxy — single route
#
####################################


@router.api_route("/{provider_id}/{path:path}", methods=["GET", "POST"])
async def proxy(
    provider_id: str,
    path: str,
    request: Request,
    user=Depends(get_code_gateway_user),
):
    """Proxy requests to the upstream provider identified by provider_id."""
    client_type = _detect_client(request)
    request.state.client_type = client_type
    log.info(f"[CG] Headers: {dict(request.headers)}")
    _check_gateway_access(request, user)
    provider_config = _get_provider_config(request, provider_id)
    _check_rate_limit(request, user.id)

    ptype = _resolve_provider_type(provider_id, provider_config)
    method = request.method
    body_bytes = await request.body() if method == "POST" else None
    body_dict = json.loads(body_bytes) if body_bytes else {}

    # [DEBUG] Body 구조 확인 (임시)
    if body_dict and client_type in ("codex-cli", "gemini-cli", "unknown"):
        _keys = list(body_dict.keys())
        _instructions = (
            body_dict.get("instructions", "")[:500]
            if body_dict.get("instructions")
            else ""
        )
        _sys_msg = ""
        for _m in body_dict.get("messages", [])[:3]:
            if isinstance(_m, dict) and _m.get("role") == "system":
                _c = _m.get("content", "")
                _sys_msg = _c[:500] if isinstance(_c, str) else str(_c)[:500]
                break
        _input_texts = []
        for _item in body_dict.get("input") or []:
            if isinstance(_item, dict) and _item.get("type") == "message":
                _content = _item.get("content", [])
                if isinstance(_content, list):
                    for _c in _content:
                        if isinstance(_c, dict) and _c.get("type") == "input_text":
                            _t = _c.get("text", "")
                            if any(
                                kw in _t.lower()
                                for kw in [
                                    "git",
                                    "repo",
                                    "remote",
                                    "cwd",
                                    "working_dir",
                                    "workspace",
                                    "project",
                                ]
                            ):
                                _input_texts.append(_t[:300])
        # Gemini API: contents 구조 확인
        _gemini_texts = []
        for _item in (body_dict.get("contents") or [])[:5]:
            if isinstance(_item, dict):
                for _part in _item.get("parts") or []:
                    if isinstance(_part, dict) and _part.get("text"):
                        _t = _part["text"]
                        if any(
                            kw in _t.lower()
                            for kw in ["cloosphere", "repo", "remote", "git"]
                        ):
                            _gemini_texts.append(_t[:300])
        _sys_inst = ""
        _si = body_dict.get("systemInstruction") or body_dict.get("system_instruction")
        if isinstance(_si, dict):
            for _p in _si.get("parts") or []:
                if isinstance(_p, dict) and _p.get("text"):
                    if (
                        "cloosphere" in _p["text"].lower()
                        or "repo" in _p["text"].lower()
                    ):
                        _sys_inst = _p["text"][:300]
        log.info(
            f"[CG][DEBUG] client={client_type}, keys={_keys}, instructions={_instructions[:200]!r}, git_related_inputs={_input_texts!r}, gemini_contents={_gemini_texts!r}, gemini_sys={_sys_inst!r}"
        )

    # Cursor Hook에서 주입한 메타데이터를 body에서 추출 후 태그 제거
    if body_dict:
        if not getattr(request.state, "repo_metadata", None):
            body_meta = _extract_repo_metadata_from_body(body_dict)
            if body_meta:
                request.state.repo_metadata = body_meta
                log.debug(f"[CG] Repo metadata from body: {body_meta}")
        _strip_repo_metadata_from_body(body_dict)

    # Repo metadata 기반 차단 검사
    _check_blocked_repos(
        request,
        user_id=user.id,
        user_email=user.email,
        user_name=user.name,
        provider_id=provider_id,
    )

    model_id = _extract_model(ptype, path, body_dict)
    is_stream = _detect_stream(ptype, path, body_dict)

    # Auto-redirect: Responses API body sent to /chat/completions endpoint.
    # Some IDE clients (e.g. Cursor) send Responses API format body (with "input"
    # field) to /v1/chat/completions, but Azure OpenAI requires the body format
    # to match the endpoint. Redirect to /responses and transform the response
    # stream back to Chat Completions format so the client can parse it.
    # Clients already using /v1/responses (e.g. Codex CLI) are not affected.
    _responses_redirect = False
    if (
        ptype == "azure_openai"
        and "chat/completions" in path
        and body_dict.get("input") is not None
    ):
        _responses_redirect = True
        path = "v1/responses"
        # Remove Chat Completions-only params that Responses API doesn't accept
        body_dict.pop("stream_options", None)
        # Remove fields not supported by Azure OpenAI Responses API
        for _unsupported in ("prompt_cache_retention",):
            body_dict.pop(_unsupported, None)
        # Apply deployment_map to model name in body (Responses API uses model
        # field for routing, not the URL path)
        deployment_map = provider_config.get("deployment_map", {})
        if deployment_map and model_id and model_id in deployment_map:
            body_dict["model"] = deployment_map[model_id]
        body_bytes = json.dumps(body_dict).encode("utf-8")
        log.info(
            f"[CG] Auto-redirect: Responses API body on /chat/completions -> "
            f"/responses (model={model_id}), body_keys={list(body_dict.keys())}"
        )

    # Model/guardrail checks for content-generation endpoints
    if method == "POST" and _is_generation_endpoint(ptype, path):
        _check_model_allowed(request, model_id)
        _check_provider_model_allowed(provider_config, model_id)

        # Check blocked file patterns
        _check_blocked_file_patterns(
            request,
            body_dict,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
            model_id=model_id or "",
            provider_id=provider_id,
        )

        if await _apply_guardrails_to_request(
            request,
            ptype,
            body_dict,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
            model_id=model_id or "",
            provider_id=provider_id,
        ):
            body_bytes = json.dumps(body_dict).encode("utf-8")

        # OpenAI-compat: inject stream_options for usage tracking
        # Responses API (v1/responses) includes usage by default, skip injection
        _is_openai_stream = ptype in ("openai", "azure_openai") or (
            ptype in ("gemini", "vertex_ai") and _is_openai_compat_path(path)
        )
        if is_stream and _is_openai_stream and "responses" not in path:
            body_dict.setdefault("stream_options", {})
            body_dict["stream_options"]["include_usage"] = True
            body_bytes = json.dumps(body_dict).encode("utf-8")

    # Models endpoint (OpenAI-compatible only)
    if method == "GET" and ptype in ("openai", "azure_openai"):
        stripped = path.rstrip("/")
        if stripped.endswith("models") and "/" not in stripped.replace(
            "models", ""
        ).strip("/"):
            return await _proxy_models_endpoint(request, provider_config, ptype)

    # Gemini/Vertex AI OpenAI-compat: sanitize request body
    if ptype in ("gemini", "vertex_ai") and _is_openai_compat_path(path) and body_dict:
        # Vertex AI requires "{publisher}/{model}" format
        # Only auto-prefix for known Gemini models; others must include publisher/
        if (
            ptype == "vertex_ai"
            and body_dict.get("model")
            and "/" not in body_dict["model"]
        ):
            model_name = body_dict["model"]
            if model_name.startswith("gemini"):
                body_dict["model"] = f"google/{model_name}"
        # Strip non-standard fields that Gemini/Vertex AI rejects
        _extra_fields = (
            "disable_thought_tag",
            "extra_body",
        )
        _dirty = False
        for field in _extra_fields:
            if field in body_dict:
                del body_dict[field]
                _dirty = True
        if _dirty or ptype == "vertex_ai":
            body_bytes = json.dumps(body_dict).encode("utf-8")

    try:
        upstream_url = _build_upstream_url(
            provider_config, ptype, path, request, model_id
        )
        headers = _build_auth_headers(provider_config, ptype, request)
    except Exception as e:
        log.error(f"[CG] URL/Header build error: {e}", exc_info=True)
        raise

    # For Gemini/Vertex AI OpenAI-compat paths, use OpenAI response parser
    resp_ptype = ptype
    if ptype in ("gemini", "vertex_ai") and _is_openai_compat_path(path):
        resp_ptype = "openai"

    # Extract request summary for detailed usage logging
    request_summary = _extract_request_summary(ptype, body_dict) if body_dict else None

    log.info(
        f"[CG] Proxy: {method} {path} -> {upstream_url}, "
        f"stream={is_stream}, model={model_id}, ptype={ptype}, "
        f"client={client_type}, user={user.email}"
    )

    # Execute proxy
    # When output guardrails are active, force non-stream to buffer the full
    # response for guardrail checking before sending to client.
    if is_stream and _has_output_guardrails(request, user_id=user.id):
        log.info(
            "[CG] Output guardrails active — forcing non-stream for guardrail check"
        )
        # Remove stream flag so upstream returns full response
        if body_dict:
            body_dict["stream"] = False
            body_bytes = json.dumps(body_dict).encode("utf-8")
        is_stream = False

    if is_stream:
        return await _stream_proxy(
            upstream_url,
            method,
            headers,
            body_bytes,
            resp_ptype,
            user.id,
            model_id,
            provider_id,
            request,
            request_summary,
            transform_to_completions=_responses_redirect,
        )
    else:
        return await _non_stream_proxy(
            upstream_url,
            method,
            headers,
            body_bytes,
            resp_ptype,
            user.id,
            model_id,
            provider_id,
            request_summary,
            request=request,
        )


####################################
#
# Access & validation
#
####################################


def _check_gateway_access(request: Request, user) -> None:
    if not request.app.state.config.ENABLE_CODE_GATEWAY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Code Gateway is disabled",
        )
    if user.role != "admin" and not has_permission(
        user.id,
        "features.code_gateway",
        request.app.state.config.USER_PERMISSIONS,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Code Gateway access not permitted",
        )


def _get_provider_config(request: Request, provider_id: str) -> dict:
    providers = request.app.state.config.CODE_GATEWAY_PROVIDERS
    config = providers.get(provider_id)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_id}' not found",
        )
    if not config.get("enable"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Provider '{provider_id}' is disabled",
        )
    ptype = config.get("type", "")
    if ptype == "vertex_ai":
        # Vertex AI uses project_id + service_account_key (or global key)
        if not config.get("project_id"):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider '{provider_id}' is missing project_id",
            )
        if not config.get("service_account_key") and not config.get(
            "use_global_gcp_key"
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Provider '{provider_id}' has no service account key configured",
            )
    elif not config.get("api_url") or not config.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Provider '{provider_id}' is not configured",
        )
    return config


def _check_model_allowed(request: Request, model: str) -> None:
    allowed = request.app.state.config.CODE_GATEWAY_ALLOWED_MODELS
    if allowed and model and model not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Model '{model}' is not allowed",
        )


def _check_provider_model_allowed(provider_config: dict, model: str) -> None:
    model_ids = provider_config.get("model_ids", [])
    if model_ids and model and model not in model_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Model '{model}' is not allowed for this provider",
        )


def _check_rate_limit(request: Request, user_id: str) -> None:
    limit = request.app.state.config.CODE_GATEWAY_RATE_LIMIT
    if not limit or limit <= 0:
        return
    now = time.time()
    window_start = now - 60
    _rate_limit_store[user_id] = [
        t for t in _rate_limit_store[user_id] if t > window_start
    ]
    if len(_rate_limit_store[user_id]) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    _rate_limit_store[user_id].append(now)


####################################
#
# Provider type helpers
#
####################################


def _resolve_provider_type(provider_id: str, config: dict) -> str:
    """Determine provider type. Falls back to provider_id if it's a known type."""
    ptype = config.get("type")
    if ptype and ptype in (
        "openai",
        "anthropic",
        "gemini",
        "azure_openai",
        "azure_ai_foundry",
        "vertex_ai",
    ):
        return ptype
    # Backward compat: use provider_id itself if known
    if provider_id in ("openai", "anthropic", "gemini"):
        return provider_id
    return "openai"


def _get_upstream_query_params(request: Request) -> str:
    """원본 쿼리 파라미터에서 인증용 ``key`` 를 제거하고 반환합니다."""
    params = {k: v for k, v in request.query_params.items() if k != "key"}
    if not params:
        return ""
    return "&".join(f"{k}={v}" for k, v in params.items())


def _build_upstream_url(
    config: dict, ptype: str, path: str, request: Request, model: str = ""
) -> str:
    if ptype == "vertex_ai":
        # Build Vertex AI URL from project_id + location + path
        project_id = config.get("project_id", "")
        location = config.get("location", "us-central1")
        # Determine base URL (global vs regional)
        is_global = location == "global"
        if is_global:
            base = "https://aiplatform.googleapis.com"
            api_location = "global"
        else:
            base = f"https://{location}-aiplatform.googleapis.com"
            api_location = location

        # OpenAI-compat path: route to /endpoints/openapi/...
        # e.g. v1beta/openai/chat/completions → .../endpoints/openapi/chat/completions
        if _is_openai_compat_path(path):
            openai_op = path.split("openai/", 1)[1] if "openai/" in path else ""
            url = f"{base}/v1beta1/projects/{project_id}/locations/{api_location}/endpoints/openapi/{openai_op}"
            return url

        # Path is the full path after provider_id, e.g.:
        #   v1/models/gemini-2.5-pro:generateContent
        #   v1beta/models/gemini-2.5-pro:streamGenerateContent
        # Convert to Vertex AI format
        # Preserve original API version (v1, v1beta, etc.)
        api_ver = "v1"
        if path.startswith("v1beta"):
            api_ver = "v1beta1"
        elif path.startswith("v1alpha"):
            api_ver = "v1alpha1"
        if "models/" in path:
            parts = path.split("models/", 1)
            model_path = parts[1] if len(parts) > 1 else path
            url = f"{base}/{api_ver}/projects/{project_id}/locations/{api_location}/publishers/google/models/{model_path}"
        else:
            url = f"{base}/{api_ver}/projects/{project_id}/locations/{api_location}/{path}"
        # Preserve original query params (e.g. alt=sse) — strip auth key
        original_qs = _get_upstream_query_params(request)
        if original_qs:
            url = f"{url}?{original_qs}"
        return url

    api_url = config["api_url"].rstrip("/")

    if ptype == "azure_openai":
        base = api_url.split("/openai")[0] if "/openai" in api_url else api_url
        api_version = config.get("api_version", "2024-12-01-preview")

        # Responses API: v1 model-based routing only (no deployment name)
        # Azure does not support /deployments/{name}/responses
        # Note: /openai/v1/responses does NOT use api-version query param
        if path.startswith("v1/") and "responses" in path:
            return f"{base}/openai/{path}"

        # Other endpoints: deployment-based routing
        # Resolve deployment name: deployment_map overrides, fallback to model name
        deployment_map = config.get("deployment_map", {})
        deployment = deployment_map.get(model, model) if model else ""

        # Strip v1/ prefix to get the operation path (e.g. chat/completions)
        clean_path = path.removeprefix("v1/").lstrip("/")

        if deployment:
            url = f"{base}/openai/deployments/{deployment}/{clean_path}"
        else:
            # No deployment (e.g. GET /models) — use base path
            url = f"{base}/openai/{clean_path}"

        sep = "&" if "?" in url else "?"
        return f"{url}{sep}api-version={api_version}"

    if ptype == "gemini":
        base = f"{api_url}/{path}"
        # Preserve original query params (e.g. alt=sse) — strip auth key
        original_qs = _get_upstream_query_params(request)
        key_param = f"key={config['api_key']}"
        if original_qs:
            return f"{base}?{key_param}&{original_qs}"
        return f"{base}?{key_param}"

    return f"{api_url}/{path}"


def _build_auth_headers(config: dict, ptype: str, request: Request) -> dict:
    headers = {"Content-Type": "application/json"}

    if ptype in ("openai",):
        headers["Authorization"] = f"Bearer {config['api_key']}"

    elif ptype == "anthropic":
        headers["x-api-key"] = config["api_key"]
        for hdr in ("anthropic-version", "anthropic-beta"):
            val = request.headers.get(hdr)
            if val:
                headers[hdr] = val

    elif ptype == "azure_ai_foundry":
        headers["api-key"] = config["api_key"]
        for hdr in ("anthropic-version", "anthropic-beta"):
            val = request.headers.get(hdr)
            if val:
                headers[hdr] = val

    elif ptype == "azure_openai":
        headers["api-key"] = config["api_key"]

    elif ptype == "vertex_ai":
        # Resolve service account key (individual or global)
        sa_key = config.get("service_account_key", "")
        if not sa_key and config.get("use_global_gcp_key"):
            sa_key = getattr(
                request.app.state.config, "GOOGLE_CLOUD_SERVICE_ACCOUNT_KEY", ""
            )
        if not sa_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Vertex AI: No service account key available",
            )
        from open_webui.routers.openai import _get_vertex_ai_access_token

        access_token = _get_vertex_ai_access_token(sa_key)
        headers["Authorization"] = f"Bearer {access_token}"

    # gemini: key is in URL query, no auth header needed

    return headers


def _is_openai_compat_path(path: str) -> bool:
    """Check if path uses Google's OpenAI-compatible endpoint (v1beta/openai/...)."""
    return "/openai/" in path or path.startswith("openai/")


def _detect_stream(ptype: str, path: str, body: dict) -> bool:
    if ptype in ("openai", "azure_openai", "anthropic", "azure_ai_foundry"):
        return body.get("stream", False)
    if ptype in ("gemini", "vertex_ai"):
        if _is_openai_compat_path(path):
            return body.get("stream", False)
        return "streamGenerateContent" in path
    return False


def _extract_model(ptype: str, path: str, body: dict) -> str:
    if ptype in ("openai", "azure_openai", "anthropic", "azure_ai_foundry"):
        return body.get("model", "")
    if ptype in ("gemini", "vertex_ai"):
        if _is_openai_compat_path(path):
            return body.get("model", "")
        if "models/" in path:
            parts = path.split("models/")
            if len(parts) > 1:
                return parts[1].split(":")[0]
    return ""


def _is_generation_endpoint(ptype: str, path: str) -> bool:
    if ptype in ("openai", "azure_openai"):
        return "completions" in path or "responses" in path
    if ptype in ("anthropic", "azure_ai_foundry"):
        return "messages" in path
    if ptype in ("gemini", "vertex_ai"):
        if _is_openai_compat_path(path):
            return "completions" in path
        return "GenerateContent" in path or "generateContent" in path
    return False


def _extract_user_text(ptype: str, body: dict) -> Optional[str]:
    if ptype in ("openai", "azure_openai"):
        return _extract_text_from_openai_messages(body)
    if ptype in ("anthropic", "azure_ai_foundry"):
        return _extract_text_from_anthropic_messages(body)
    if ptype in ("gemini", "vertex_ai"):
        return _extract_text_from_gemini_contents(body)
    return None


def _replace_user_text(ptype: str, body: dict, new_text: str) -> None:
    if ptype in ("openai", "azure_openai"):
        _replace_last_user_message_openai(body, new_text)
    elif ptype in ("anthropic", "azure_ai_foundry"):
        _replace_last_user_message_anthropic(body, new_text)
    elif ptype in ("gemini", "vertex_ai"):
        _replace_last_user_message_gemini(body, new_text)


####################################
#
# Guardrails
#
####################################


def _log_guardrail_violations(
    result,
    original_text: str,
    user_id: str = "",
    user_email: str = "",
    user_name: str = "",
    model_id: str = "",
    provider_id: str = "",
    client_type: str = "unknown",
) -> None:
    """Log guardrail violations (PII, blocked_word, custom_pattern) to DB."""
    try:
        from open_webui.models.guardrail_log import (
            GuardrailLogCreateForm,
            GuardrailLogs,
        )

        for v in result.violations:
            action = "block" if result.blocked else "log"
            detail_name = v.pattern_name or v.pii_type or v.type
            GuardrailLogs.insert_guardrail_log(
                GuardrailLogCreateForm(
                    user_id=user_id,
                    user_email=user_email or None,
                    user_name=user_name or None,
                    guardrail_name=f"Code Gateway PII ({detail_name})",
                    action=action,
                    detection_source=v.type,
                    detection_detail=f"{v.type}: {v.matched}",
                    original_content=original_text[:500],
                    processed_content=result.text[:500]
                    if result.text != original_text
                    else None,
                    meta={
                        "source": "code_gateway",
                        "violation_type": v.type,
                        "matched": v.matched,
                        "model_id": model_id,
                        "provider_id": provider_id,
                        "client_type": client_type,
                    },
                )
            )
    except Exception as e:
        log.error(f"[CG] Failed to log guardrail violation: {e}")


def _build_generate_func(app) -> Callable:
    """Create an async generate_func for LLM Judge guardrails.

    Returns a function compatible with pii_detector.LLMJudge.judge() signature:
        generate_func(model, messages, max_tokens, temperature) -> dict
    """

    async def _generate(
        model: str,
        messages: list,
        max_tokens: int = 100,
        temperature: float = 0,
        **kwargs,
    ) -> dict:
        from extension_modules.utils.llm import create_llm_from_app
        from langchain_core.messages import HumanMessage

        llm = create_llm_from_app(
            app, model, temperature=temperature, max_tokens=max_tokens
        )
        if not llm:
            raise ValueError(f"LLM Judge model not found: {model}")

        lc_messages = []
        for msg in messages:
            if msg.get("role") == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))

        response = await llm.ainvoke(lc_messages)
        content = response.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )

        return {"choices": [{"message": {"content": content}}]}

    return _generate


def _get_cg_source_guardrail_ids(request: Request) -> list[str]:
    """Build source guardrail IDs for Code Gateway.

    Combines CODE_GATEWAY_GUARDRAIL_IDS with global guardrail IDs
    when follow_global_guardrail is enabled.
    """
    cg_ids = list(request.app.state.config.CODE_GATEWAY_GUARDRAIL_IDS or [])

    follow_global = getattr(
        request.app.state.config, "CODE_GATEWAY_FOLLOW_GLOBAL_GUARDRAIL", False
    )
    if hasattr(follow_global, "value"):
        follow_global = follow_global.value

    if follow_global:
        global_enabled = getattr(
            request.app.state.config, "ENABLE_GLOBAL_GUARDRAIL", False
        )
        if hasattr(global_enabled, "value"):
            global_enabled = global_enabled.value
        global_ids = getattr(request.app.state.config, "GLOBAL_GUARDRAIL_IDS", [])
        if hasattr(global_ids, "value"):
            global_ids = global_ids.value
        if global_ids:
            for gid in global_ids:
                if gid not in cg_ids:
                    cg_ids.append(gid)

    return cg_ids


async def _apply_guardrails_to_request(
    request: Request,
    ptype: str,
    body_dict: dict,
    user_id: str = "",
    user_email: str = "",
    user_name: str = "",
    model_id: str = "",
    provider_id: str = "",
) -> bool:
    """Apply guardrails to ALL text in the request body.

    Processes user messages, tool results, function outputs — everything.
    Supports both rule-based and LLM Judge guardrails.
    Returns True if body_dict was modified (caller should re-encode).
    """
    from open_webui.utils.guardrails import get_effective_guardrail_ids

    cg_ids = _get_cg_source_guardrail_ids(request)
    guardrail_ids = get_effective_guardrail_ids(
        user_id=user_id,
        request=request,
        source_guardrail_ids=cg_ids,
    )
    log.info(f"[CG] Guardrail IDs: {guardrail_ids}")
    if not guardrail_ids:
        return False

    from extension_modules.guardrail.pii_detector import (
        apply_guardrails_with_llm as run_guardrails,
    )
    from open_webui.models.guardrails import Guardrails

    guardrails = Guardrails.get_guardrails_by_ids(guardrail_ids)
    configs = [g.model_dump() for g in guardrails]
    log.debug(f"[CG] Guardrail configs loaded: {len(configs)} guardrails")
    if not configs:
        return False

    # LLM Judge용 generate_func 생성 (llm_judge_enabled인 config이 있을 때만)
    generate_func = None
    has_llm_judge = any(c.get("llm_judge_enabled") for c in configs)
    if has_llm_judge:
        generate_func = _build_generate_func(request.app)

    modified = False

    req_client_type = getattr(request.state, "client_type", "unknown")

    async def _process(text: str) -> str:
        """Run guardrails on a text segment. Raises on block."""
        nonlocal modified
        if not text or not text.strip():
            return text
        result = await run_guardrails(
            configs, text, is_input=True, generate_func=generate_func
        )
        if result.has_violations:
            _log_guardrail_violations(
                result,
                original_text=text,
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                model_id=model_id,
                provider_id=provider_id,
                client_type=req_client_type,
            )
        if result.text != text:
            log.info(f"[CG] Guardrail redacted: {text[:80]!r}")
        if result.blocked:
            raise HTTPException(
                status_code=451,
                detail=f"Guardrail blocked the request: {result.block_reason}",
            )
        if result.text != text:
            modified = True
        return result.text

    # --- Responses API (input field) ---
    input_field = body_dict.get("input")
    if isinstance(input_field, str):
        body_dict["input"] = await _process(input_field)
    elif isinstance(input_field, list):
        for item in input_field:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type", "")
            # User/assistant message content
            content = item.get("content")
            if isinstance(content, str):
                item["content"] = await _process(content)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        if text:
                            part["text"] = await _process(text)
            # function_call_output
            if item_type == "function_call_output":
                output = item.get("output", "")
                if isinstance(output, str):
                    item["output"] = await _process(output)

    # --- Chat Completions API (messages) ---
    for msg in body_dict.get("messages", []):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = await _process(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    text = part.get("text", "")
                    if text:
                        part["text"] = await _process(text)

    # --- Gemini API (contents) ---
    for item in body_dict.get("contents", []):
        if not isinstance(item, dict):
            continue
        for part in item.get("parts", []):
            if not isinstance(part, dict):
                continue
            text = part.get("text")
            if isinstance(text, str):
                part["text"] = await _process(text)
            # functionResponse output
            fr = part.get("functionResponse")
            if fr and isinstance(fr.get("response"), dict):
                resp = fr["response"]
                for key in ("output", "result"):
                    val = resp.get(key)
                    if isinstance(val, str):
                        resp[key] = await _process(val)

    return modified


def _has_output_guardrails(request: Request, user_id: str = "") -> bool:
    """Check if any configured guardrail has apply_to_output enabled."""
    from open_webui.utils.guardrails import get_effective_guardrail_ids

    cg_ids = _get_cg_source_guardrail_ids(request)
    guardrail_ids = get_effective_guardrail_ids(
        user_id=user_id,
        request=request,
        source_guardrail_ids=cg_ids,
    )
    if not guardrail_ids:
        return False
    from open_webui.models.guardrails import Guardrails

    guardrails = Guardrails.get_guardrails_by_ids(guardrail_ids)
    return any(g.apply_to_output for g in guardrails)


async def _apply_guardrails_to_response(
    request: Request,
    text: str,
    user_id: str = "",
    user_email: str = "",
    user_name: str = "",
    model_id: str = "",
    provider_id: str = "",
) -> tuple[str, bool]:
    """Apply output guardrails to LLM response text.

    Returns (processed_text, blocked). If blocked, the text should be replaced
    with an error message.
    """
    from open_webui.utils.guardrails import get_effective_guardrail_ids

    cg_ids = _get_cg_source_guardrail_ids(request)
    guardrail_ids = get_effective_guardrail_ids(
        user_id=user_id,
        request=request,
        source_guardrail_ids=cg_ids,
    )
    if not guardrail_ids or not text or not text.strip():
        return text, False

    from extension_modules.guardrail.pii_detector import (
        apply_guardrails_with_llm as run_guardrails,
    )
    from open_webui.models.guardrails import Guardrails

    guardrails = Guardrails.get_guardrails_by_ids(guardrail_ids)
    configs = [g.model_dump() for g in guardrails]
    if not configs:
        return text, False

    generate_func = None
    has_llm_judge = any(c.get("llm_judge_enabled") for c in configs)
    if has_llm_judge:
        generate_func = _build_generate_func(request.app)

    result = await run_guardrails(
        configs, text, is_input=False, generate_func=generate_func
    )

    req_client_type = getattr(request.state, "client_type", "unknown")
    if result.has_violations:
        _log_guardrail_violations(
            result,
            original_text=text,
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            model_id=model_id,
            provider_id=provider_id,
            client_type=req_client_type,
        )

    if result.blocked:
        return result.block_reason or "Guardrail blocked the response", True

    return result.text, False


def _check_blocked_file_patterns(
    request: Request,
    body_dict: dict,
    user_id: str = "",
    user_email: str = "",
    user_name: str = "",
    model_id: str = "",
    provider_id: str = "",
) -> None:
    """Check if the request references blocked file patterns. Block or warn based on config."""
    patterns = request.app.state.config.CODE_GATEWAY_BLOCKED_FILE_PATTERNS
    log.debug(f"[CG] blocked_file_patterns={patterns}")
    if not patterns:
        return

    action = getattr(
        request.app.state.config, "CODE_GATEWAY_BLOCKED_FILE_ACTION", "block"
    )

    # Collect file paths from tool/function call arguments only.
    # We intentionally skip tool outputs (function_call_output, role=tool,
    # functionResponse) and user text to avoid false positives — file contents
    # or Cursor's open-file context may mention blocked patterns like ".env"
    # in code comments, config examples, etc.
    paths_to_check: list[str] = []

    # Responses API (Codex CLI, Cursor): function_call arguments
    input_field = body_dict.get("input")
    if isinstance(input_field, list):
        for item in input_field:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "function_call":
                args_str = item.get("arguments", "")
                _collect_paths_from_args(args_str, paths_to_check)

    # Chat Completions (Claude Code, Cursor): tool_calls arguments
    for msg in body_dict.get("messages", []):
        if not isinstance(msg, dict):
            continue
        for tc in msg.get("tool_calls", []):
            args_str = tc.get("function", {}).get("arguments", "")
            _collect_paths_from_args(args_str, paths_to_check)

    # Gemini API (Gemini CLI): functionCall args
    for item in body_dict.get("contents", []):
        if not isinstance(item, dict):
            continue
        for part in item.get("parts", []):
            if not isinstance(part, dict):
                continue
            fc = part.get("functionCall")
            if fc and isinstance(fc.get("args"), dict):
                _collect_paths_from_args(json.dumps(fc["args"]), paths_to_check)

    if paths_to_check:
        log.debug(
            f"[CG] File pattern check: {len(paths_to_check)} texts, patterns={patterns}"
        )

    if not paths_to_check:
        return

    # Check each path against blocked patterns
    for text in paths_to_check:
        matched = _match_file_pattern(text, patterns)
        if matched:
            _log_file_pattern_match(
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                pattern=matched,
                matched_text=text,
                action=action,
                model_id=model_id,
                provider_id=provider_id,
                client_type=getattr(request.state, "client_type", "unknown"),
            )
            if action == "block":
                raise HTTPException(
                    status_code=451,
                    detail=f"Access to file matching blocked pattern '{matched}' is not allowed",
                )
            else:
                return  # Log once, don't block further


def _log_file_pattern_match(
    user_id: str,
    pattern: str,
    matched_text: str,
    action: str,
    user_email: str = "",
    user_name: str = "",
    model_id: str = "",
    provider_id: str = "",
    client_type: str = "unknown",
) -> None:
    """Log file pattern match to guardrail log table."""
    try:
        from open_webui.models.guardrail_log import (
            GuardrailLogCreateForm,
            GuardrailLogs,
        )

        GuardrailLogs.insert_guardrail_log(
            GuardrailLogCreateForm(
                user_id=user_id,
                user_email=user_email or None,
                user_name=user_name or None,
                guardrail_name="Code Gateway File Pattern",
                action=action,
                detection_source="blocked_word",
                detection_detail=f"pattern: {pattern}",
                original_content=matched_text,
                meta={
                    "source": "code_gateway",
                    "pattern": pattern,
                    "model_id": model_id,
                    "provider_id": provider_id,
                    "client_type": client_type,
                },
            )
        )
    except Exception as e:
        log.error(f"[CG] Failed to log file pattern match: {e}")


def _check_blocked_repos(
    request: Request,
    user_id: str = "",
    user_email: str = "",
    user_name: str = "",
    provider_id: str = "",
) -> None:
    """리포지토리 메타데이터를 기반으로 차단 정책을 검사합니다."""
    metadata = getattr(request.state, "repo_metadata", None)
    require_metadata = getattr(
        request.app.state.config, "CODE_GATEWAY_REQUIRE_REPO_METADATA", False
    )
    missing_action = getattr(
        request.app.state.config, "CODE_GATEWAY_MISSING_METADATA_ACTION", "allow"
    )
    blocked_repos: list[str] = getattr(
        request.app.state.config, "CODE_GATEWAY_BLOCKED_REPOS", []
    )

    # 메타데이터 누락 정책 검사 (require_repo_metadata 또는 missing_metadata_action)
    if not metadata and (require_metadata or missing_action in ("warn", "block")):
        if missing_action == "block" or require_metadata:
            _client = getattr(request.state, "client_type", "unknown")
            _log_missing_metadata(
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                action="block",
                provider_id=provider_id,
                client_type=_client,
            )
            log.warning(
                f"[CG] Repo metadata missing (blocked): user={user_id}, client={_client}"
            )
            raise HTTPException(
                status_code=451,
                detail="Repository metadata is required. Please install the Cloosphere Cursor Hook or helper script.",
            )
        if missing_action == "warn":
            _client = getattr(request.state, "client_type", "unknown")
            _log_missing_metadata(
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                action="warn",
                provider_id=provider_id,
                client_type=_client,
            )
            log.warning(
                f"[CG] Repo metadata missing (warn): user={user_id}, client={_client}"
            )

    if not metadata or not blocked_repos:
        return

    # repo_urls 리스트 지원 (하위 호환: 문자열, pipe 구분, 단일 값 모두 처리)
    raw_urls = metadata.get("repo_urls", [])
    if isinstance(raw_urls, str):
        # 문자열이면 pipe(|) 구분 리스트로 분리
        repo_urls = [u for u in raw_urls.split("|") if u]
    elif isinstance(raw_urls, list):
        repo_urls = raw_urls
    else:
        repo_urls = []
    if not repo_urls:
        single = metadata.get("repo_url", "") or metadata.get("git_remote", "") or ""
        if single:
            repo_urls = [single]
    working_dir = metadata.get("working_dir", "") or metadata.get("cwd", "") or ""

    if not repo_urls and not working_dir:
        return

    def _normalize_url(url: str) -> str:
        """다양한 git URL 형식을 통일된 형태로 정규화합니다.

        Azure DevOps:
          git@ssh.dev.azure.com:v3/{org}/{project}/{repo}
          https://{user}@dev.azure.com/{org}/{project}/_git/{repo}
          → dev.azure.com/{org}/{project}/{repo}

        GitHub/GitLab/Bitbucket:
          git@github.com:org/repo.git
          https://github.com/org/repo.git
          → github.com/org/repo
        """
        result = url.strip()

        # Azure DevOps SSH: git@ssh.dev.azure.com:v3/{org}/{project}/{repo}
        ado_ssh = re.match(
            r"^git@ssh\.dev\.azure\.com[:/]v3/([^/]+)/([^/]+)/(.+?)(?:\.git)?$",
            result,
        )
        if ado_ssh:
            return f"dev.azure.com/{ado_ssh.group(1)}/{ado_ssh.group(2)}/{ado_ssh.group(3)}"

        # Azure DevOps HTTPS: https://{user}@dev.azure.com/{org}/{project}/_git/{repo}
        ado_https = re.match(
            r"^https?://(?:[^@]+@)?dev\.azure\.com/([^/]+)/([^/]+)/_git/(.+?)(?:\.git)?$",
            result,
        )
        if ado_https:
            return f"dev.azure.com/{ado_https.group(1)}/{ado_https.group(2)}/{ado_https.group(3)}"

        # 일반: prefix 제거, : → /, .git 제거
        for prefix in ("https://", "http://", "ssh://", "git@"):
            if result.startswith(prefix):
                result = result[len(prefix) :]
        result = result.replace(":", "/")
        return result.removesuffix(".git")

    for pattern in blocked_repos:
        p = pattern.strip()
        if not p:
            continue
        normalized_pattern = _normalize_url(p)
        pattern_lower = normalized_pattern.lower()

        matched = False
        matched_url = ""
        for url in repo_urls:
            normalized = _normalize_url(url)
            if pattern_lower in normalized.lower() or pattern_lower in url.lower():
                matched = True
                matched_url = url
                break
        if not matched and working_dir and pattern_lower in working_dir.lower():
            matched = True

        if matched:
            _log_blocked_repo(
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                pattern=p,
                repo_url=matched_url or ", ".join(repo_urls),
                working_dir=working_dir,
                provider_id=provider_id,
                client_type=getattr(request.state, "client_type", "unknown"),
            )
            raise HTTPException(
                status_code=451,
                detail=f"AI coding tool usage is blocked for repository matching '{p}'",
            )


def _log_blocked_repo(
    user_id: str,
    pattern: str,
    repo_url: str,
    working_dir: str,
    user_email: str = "",
    user_name: str = "",
    provider_id: str = "",
    client_type: str = "unknown",
) -> None:
    """차단된 리포지토리 접근을 가드레일 로그에 기록합니다."""
    try:
        from open_webui.models.guardrail_log import (
            GuardrailLogCreateForm,
            GuardrailLogs,
        )

        GuardrailLogs.insert_guardrail_log(
            GuardrailLogCreateForm(
                user_id=user_id,
                user_email=user_email or None,
                user_name=user_name or None,
                guardrail_name="Code Gateway Blocked Repository",
                action="block",
                detection_source="blocked_repo",
                detection_detail=f"pattern: {pattern}",
                original_content=f"repo: {repo_url}, dir: {working_dir}",
                meta={
                    "source": "code_gateway",
                    "pattern": pattern,
                    "repo_url": repo_url,
                    "working_dir": working_dir,
                    "provider_id": provider_id,
                    "client_type": client_type,
                },
            )
        )
    except Exception as e:
        log.error(f"[CG] Failed to log blocked repo: {e}")


def _log_missing_metadata(
    user_id: str,
    user_email: str = "",
    user_name: str = "",
    action: str = "warn",
    provider_id: str = "",
    client_type: str = "unknown",
) -> None:
    """메타데이터 누락을 가드레일 로그에 기록합니다."""
    try:
        from open_webui.models.guardrail_log import (
            GuardrailLogCreateForm,
            GuardrailLogs,
        )

        GuardrailLogs.insert_guardrail_log(
            GuardrailLogCreateForm(
                user_id=user_id,
                user_email=user_email or None,
                user_name=user_name or None,
                guardrail_name="Code Gateway Missing Metadata",
                action=action,
                detection_source="missing_metadata",
                detection_detail="Repository metadata not provided",
                original_content="",
                meta={
                    "source": "code_gateway",
                    "provider_id": provider_id,
                    "client_type": client_type,
                },
            )
        )
    except Exception as e:
        log.error(f"[CG] Failed to log missing metadata: {e}")


def _match_file_pattern(text: str, patterns: list[str]) -> Optional[str]:
    """Check text against file patterns. Returns matched pattern or None."""
    import fnmatch

    text_lower = text.lower()
    for pattern in patterns:
        normalized = pattern.strip()
        if not normalized:
            continue
        pattern_lower = normalized.lower()

        if not any(c in normalized for c in ("*", "?")):
            # Exact name: ".env", "id_rsa", "credentials.json"
            if pattern_lower in text_lower:
                return normalized
        else:
            # Glob: "*.pem", "*.key", ".env*"
            for segment in text.replace("\\", "/").split("/"):
                segment = segment.strip().strip('"').strip("'")
                if fnmatch.fnmatch(segment.lower(), pattern_lower):
                    return normalized
    return None


def _collect_paths_from_args(args_str: str, paths: list[str]) -> None:
    """Extract file path and command values from a JSON arguments string.

    Checks path-like keys used by major AI coding tools:
    - Claude Code: file_path, path, command
    - Codex CLI: file_path, dir_path, command
    - Gemini CLI: path, file_path, command
    - Cursor: target_file, relative_workspace_path, command
    """
    if not args_str:
        return
    try:
        args = json.loads(args_str)
        if isinstance(args, dict):
            # File/directory path keys (no size limit)
            for key in (
                "path",
                "file_path",
                "filename",
                "file",
                "target",
                "target_file",
                "dir_path",
                "relative_workspace_path",
            ):
                if key in args and isinstance(args[key], str):
                    paths.append(args[key])
            # Shell command keys (may contain "cat .env", "rm secret.key", etc.)
            for key in ("command", "cmd"):
                if key in args and isinstance(args[key], str):
                    paths.append(args[key])
    except (json.JSONDecodeError, TypeError):
        pass


####################################
#
# Text extraction / replacement
#
####################################


def _extract_text_from_openai_messages(body: dict) -> Optional[str]:
    # Responses API: "input" field (string or message list)
    input_field = body.get("input")
    if input_field is not None:
        if isinstance(input_field, str):
            return input_field
        if isinstance(input_field, list):
            for msg in reversed(input_field):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        return content
            return None

    # Chat Completions API: "messages" field
    messages = body.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                return " ".join(texts) if texts else None
    return None


def _extract_text_from_anthropic_messages(body: dict) -> Optional[str]:
    messages = body.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                return " ".join(texts) if texts else None
    return None


def _extract_text_from_gemini_contents(body: dict) -> Optional[str]:
    contents = body.get("contents", [])
    for item in reversed(contents):
        if item.get("role") == "user":
            parts = item.get("parts", [])
            texts = [
                p.get("text", "") for p in parts if isinstance(p, dict) and "text" in p
            ]
            return " ".join(texts) if texts else None
    return None


def _replace_last_user_message_openai(body: dict, new_text: str) -> None:
    messages = body.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            if isinstance(msg.get("content"), str):
                msg["content"] = new_text
            elif isinstance(msg.get("content"), list):
                for part in msg["content"]:
                    if isinstance(part, dict) and part.get("type") == "text":
                        part["text"] = new_text
                        return
            return


def _replace_last_user_message_anthropic(body: dict, new_text: str) -> None:
    messages = body.get("messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                msg["content"] = new_text
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        part["text"] = new_text
                        return
            return


def _replace_last_user_message_gemini(body: dict, new_text: str) -> None:
    contents = body.get("contents", [])
    for item in reversed(contents):
        if item.get("role") == "user":
            parts = item.get("parts", [])
            for part in parts:
                if isinstance(part, dict) and "text" in part:
                    part["text"] = new_text
                    return
            return


####################################
#
# Usage tracking
#
####################################


def _record_usage(
    user_id: str,
    model_id: str,
    usage_data: Optional[dict],
    provider_id: str,
    tool_calls: Optional[list[dict]] = None,
) -> None:
    if not usage_data:
        return
    try:
        Usages.insert_new_usage(
            user_id=user_id,
            chat_id=None,
            model_id=model_id,
            message_id=f"cg:{uuid.uuid4().hex[:12]}",
            message_type=UsageMessageType.CODE_GATEWAY,
            total_tokens=usage_data.get("total_tokens", 0),
            usage=usage_data,
            tool_calls=tool_calls,
        )
    except Exception as e:
        log.error(f"Failed to record code gateway usage: {e}")


def _extract_request_summary(ptype: str, body_dict: dict) -> dict:
    """Extract request summary (input preview, message count, tools) for logging."""
    summary: dict = {}

    # Detect tools/functions in request
    tools = body_dict.get("tools")
    if tools and isinstance(tools, list):
        summary["tools_count"] = len(tools)

    # OpenAI / Azure OpenAI
    if ptype in ("openai", "azure_openai"):
        # Responses API: input field
        input_field = body_dict.get("input")
        if input_field is not None:
            if isinstance(input_field, str):
                summary["input_preview"] = input_field
                summary["message_count"] = 1
                return summary
            if isinstance(input_field, list):
                summary["message_count"] = len(input_field)
                for msg in reversed(input_field):
                    if isinstance(msg, dict) and msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            summary["input_preview"] = content
                        elif isinstance(content, list):
                            texts = [
                                p.get("text", "")
                                for p in content
                                if isinstance(p, dict)
                                and p.get("type") in ("text", "input_text")
                            ]
                            summary["input_preview"] = " ".join(texts)
                        break
                return summary
        # Chat Completions API
        messages = body_dict.get("messages", [])
        summary["message_count"] = len(messages)
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    summary["input_preview"] = content
                elif isinstance(content, list):
                    texts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    summary["input_preview"] = " ".join(texts)
                break

    elif ptype in ("anthropic", "azure_ai_foundry"):
        messages = body_dict.get("messages", [])
        summary["message_count"] = len(messages)
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    summary["input_preview"] = content
                elif isinstance(content, list):
                    texts = [
                        p.get("text", "")
                        for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    ]
                    summary["input_preview"] = " ".join(texts)
                break

    elif ptype in ("gemini", "vertex_ai"):
        # OpenAI-compat path uses messages, native Gemini uses contents
        if body_dict.get("messages"):
            messages = body_dict.get("messages", [])
            summary["message_count"] = len(messages)
            for msg in reversed(messages):
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        summary["input_preview"] = content
                    elif isinstance(content, list):
                        texts = [
                            p.get("text", "")
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        summary["input_preview"] = " ".join(texts)
                    break
        else:
            contents = body_dict.get("contents", [])
            summary["message_count"] = len(contents)
            for item in reversed(contents):
                if isinstance(item, dict) and item.get("role") == "user":
                    parts = item.get("parts", [])
                    texts = [
                        p.get("text", "")
                        for p in parts
                        if isinstance(p, dict) and "text" in p
                    ]
                    summary["input_preview"] = " ".join(texts)
                    break

    return summary


def _update_stream_data(
    ptype: str, chunk_str: str, usage_data: dict, content_data: dict
) -> None:
    """Parse an SSE chunk, accumulate token usage and response content."""
    if ptype in ("openai", "azure_openai"):
        for line in chunk_str.split("\n"):
            if not line.startswith("data: ") or line == "data: [DONE]":
                continue
            json_str = line[6:].strip()
            if not json_str:
                continue
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "")

            # Chat Completions: usage at top level
            if "usage" in data and data["usage"]:
                usage_data.update(data["usage"])

            # Chat Completions: content deltas
            if "choices" in data:
                for choice in data["choices"]:
                    delta = choice.get("delta", {})
                    if delta.get("content"):
                        prev = content_data.get("output_text", "")
                        content_data["output_text"] = prev + delta["content"]
                    if "tool_calls" in delta:
                        acc = content_data.setdefault("_tc_acc", {})
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if tc.get("id"):
                                acc[idx] = {
                                    "name": tc.get("function", {}).get("name", ""),
                                    "call_id": tc.get("id", ""),
                                    "arguments": tc.get("function", {}).get(
                                        "arguments", ""
                                    ),
                                }
                            elif idx in acc:
                                acc[idx]["arguments"] += tc.get("function", {}).get(
                                    "arguments", ""
                                )
                    if choice.get("finish_reason"):
                        content_data["finish_reason"] = choice["finish_reason"]

            # Responses API: response.completed has everything
            if event_type == "response.completed":
                resp = data.get("response", {})
                if resp.get("usage"):
                    usage_data.update(resp["usage"])
                output_texts = []
                for item in resp.get("output", []):
                    item_type = item.get("type", "")
                    if item_type == "message":
                        for part in item.get("content", []):
                            if part.get("type") == "output_text":
                                output_texts.append(part.get("text", ""))
                    elif item_type == "function_call":
                        content_data.setdefault("tool_calls", []).append(
                            {
                                "name": item.get("name", ""),
                                "call_id": item.get("call_id", ""),
                                "arguments": item.get("arguments", ""),
                            }
                        )
                if output_texts:
                    content_data["output_text"] = "\n".join(output_texts)
                content_data["finish_reason"] = resp.get("status", "")

    elif ptype in ("anthropic", "azure_ai_foundry"):
        for line in chunk_str.split("\n"):
            if not line.startswith("data: "):
                continue
            json_str = line[6:].strip()
            if not json_str:
                continue
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type", "")

            if event_type == "message_start":
                msg = data.get("message", {})
                if msg.get("usage"):
                    usage_data.update(msg["usage"])
            elif event_type == "message_delta":
                if data.get("usage"):
                    usage_data.update(data["usage"])
                stop = data.get("delta", {}).get("stop_reason")
                if stop:
                    content_data["finish_reason"] = stop
            elif event_type == "content_block_start":
                block = data.get("content_block", {})
                if block.get("type") == "tool_use":
                    idx = data.get("index", 0)
                    content_data.setdefault("_tc_acc", {})[idx] = {
                        "name": block.get("name", ""),
                        "call_id": block.get("id", ""),
                        "arguments": "",
                    }
            elif event_type == "content_block_delta":
                delta = data.get("delta", {})
                if delta.get("type") == "text_delta":
                    prev = content_data.get("output_text", "")
                    content_data["output_text"] = prev + delta.get("text", "")
                elif delta.get("type") == "input_json_delta":
                    idx = data.get("index", 0)
                    acc = content_data.get("_tc_acc", {})
                    if idx in acc:
                        acc[idx]["arguments"] += delta.get("partial_json", "")

    elif ptype in ("gemini", "vertex_ai"):
        for line in chunk_str.split("\n"):
            stripped = line.strip().strip(",[]")
            if not stripped or not stripped.startswith("{"):
                continue
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            meta = data.get("usageMetadata")
            if meta:
                usage_data.update(
                    {
                        "input_tokens": meta.get("promptTokenCount", 0),
                        "output_tokens": meta.get("candidatesTokenCount", 0),
                        "total_tokens": meta.get("totalTokenCount", 0),
                    }
                )
            for candidate in data.get("candidates", []):
                content = candidate.get("content", {})
                for part in content.get("parts", []):
                    if "text" in part:
                        prev = content_data.get("output_text", "")
                        content_data["output_text"] = prev + part["text"]
                    if "functionCall" in part:
                        fc = part["functionCall"]
                        content_data.setdefault("tool_calls", []).append(
                            {
                                "name": fc.get("name", ""),
                                "arguments": json.dumps(fc.get("args", {})),
                            }
                        )


def _finalize_content_data(content_data: dict) -> dict:
    """Resolve accumulated tool calls."""
    result: dict = {}

    if "output_text" in content_data:
        result["output_text"] = content_data["output_text"]
    # Merge tool_calls from direct list and accumulator
    tool_calls = list(content_data.get("tool_calls", []))
    if "_tc_acc" in content_data:
        for idx in sorted(content_data["_tc_acc"].keys()):
            tc = content_data["_tc_acc"][idx]
            tool_calls.append(tc)
    if tool_calls:
        result["tool_calls"] = tool_calls
    if "finish_reason" in content_data:
        result["finish_reason"] = content_data["finish_reason"]

    return result


def _extract_response_usage(ptype: str, resp_json: dict) -> Optional[dict]:
    """Extract usage from a non-streaming response body."""
    if ptype in ("openai", "azure_openai"):
        return resp_json.get("usage")

    if ptype in ("anthropic", "azure_ai_foundry"):
        usage = resp_json.get("usage")
        if usage:
            total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
            usage["total_tokens"] = total
        return usage

    if ptype in ("gemini", "vertex_ai"):
        meta = resp_json.get("usageMetadata")
        if meta:
            return {
                "input_tokens": meta.get("promptTokenCount", 0),
                "output_tokens": meta.get("candidatesTokenCount", 0),
                "total_tokens": meta.get("totalTokenCount", 0),
            }

    return None


def _extract_response_content(ptype: str, resp_json: dict) -> dict:
    """Extract response content (text + tool calls) from non-streaming response."""
    content: dict = {}

    if ptype in ("openai", "azure_openai"):
        # Chat Completions
        choices = resp_json.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            if msg.get("content"):
                content["output_text"] = msg["content"]
            if msg.get("tool_calls"):
                content["tool_calls"] = [
                    {
                        "name": tc.get("function", {}).get("name", ""),
                        "call_id": tc.get("id", ""),
                        "arguments": tc.get("function", {}).get("arguments", ""),
                    }
                    for tc in msg["tool_calls"]
                ]
            content["finish_reason"] = choices[0].get("finish_reason", "")
        # Responses API
        output = resp_json.get("output", [])
        if output:
            texts = []
            tool_calls = []
            for item in output:
                if item.get("type") == "message":
                    for part in item.get("content", []):
                        if part.get("type") == "output_text":
                            texts.append(part.get("text", ""))
                elif item.get("type") == "function_call":
                    tool_calls.append(
                        {
                            "name": item.get("name", ""),
                            "call_id": item.get("call_id", ""),
                            "arguments": item.get("arguments", ""),
                        }
                    )
            if texts:
                content["output_text"] = "\n".join(texts)
            if tool_calls:
                content["tool_calls"] = tool_calls
            content["finish_reason"] = resp_json.get("status", "")

    elif ptype in ("anthropic", "azure_ai_foundry"):
        blocks = resp_json.get("content", [])
        texts = []
        tool_calls = []
        for block in blocks:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                tool_calls.append(
                    {
                        "name": block.get("name", ""),
                        "call_id": block.get("id", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    }
                )
        if texts:
            content["output_text"] = "\n".join(texts)
        if tool_calls:
            content["tool_calls"] = tool_calls
        content["finish_reason"] = resp_json.get("stop_reason", "")

    elif ptype in ("gemini", "vertex_ai"):
        candidates = resp_json.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            texts = []
            tool_calls = []
            for part in parts:
                if "text" in part:
                    texts.append(part["text"])
                if "functionCall" in part:
                    fc = part["functionCall"]
                    tool_calls.append(
                        {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args", {})),
                        }
                    )
            if texts:
                content["output_text"] = "\n".join(texts)
            if tool_calls:
                content["tool_calls"] = tool_calls
    return content


def _replace_response_content(ptype: str, resp_json: dict, new_text: str) -> None:
    """Replace the text content in a non-streaming response with guardrail-processed text."""
    if ptype in ("openai", "azure_openai"):
        choices = resp_json.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            if msg.get("content") is not None:
                msg["content"] = new_text
        # Responses API
        output = resp_json.get("output", [])
        for item in output:
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        part["text"] = new_text
                        return
    elif ptype in ("anthropic", "azure_ai_foundry"):
        for block in resp_json.get("content", []):
            if block.get("type") == "text":
                block["text"] = new_text
                return
    elif ptype in ("gemini", "vertex_ai"):
        candidates = resp_json.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    part["text"] = new_text
                    return


def _build_enriched_usage(
    usage_data: dict,
    provider_id: str,
    request_summary: Optional[dict],
    content: Optional[dict],
    client_type: str = "unknown",
) -> dict:
    """Build enriched usage dict with provider, request summary, and response content."""
    enriched = {**usage_data, "provider": provider_id, "client_type": client_type}

    if request_summary:
        enriched["request_summary"] = request_summary

    if content:
        if content.get("output_text"):
            enriched["output_preview"] = content["output_text"]
        if content.get("finish_reason"):
            enriched["finish_reason"] = content["finish_reason"]

    # Extract token details (cached, reasoning tokens)
    token_details: dict = {}
    if usage_data.get("input_tokens_details"):
        token_details["input"] = usage_data["input_tokens_details"]
    if usage_data.get("output_tokens_details"):
        token_details["output"] = usage_data["output_tokens_details"]
    if token_details:
        enriched["token_details"] = token_details

    return enriched


####################################
#
# Responses API → Chat Completions stream transform
#
####################################


def _build_cc_chunk(
    chunk_id: str,
    created: int,
    model: str,
    delta: dict,
    finish_reason: Optional[str] = None,
) -> dict:
    """Build a single Chat Completions SSE chunk."""
    return {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


async def _transform_responses_stream(
    response: aiohttp.ClientResponse,
    model_id: str,
    usage_data: dict,
    content_data: dict,
):
    """Transform Responses API SSE events into Chat Completions SSE chunks.

    Enables IDE clients (e.g. Cursor) that only understand Chat Completions
    streaming format to work with Azure models that require the Responses API.
    """
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    sent_role = False
    tool_call_index = -1

    any_yielded = False
    buffer = ""
    async for raw_chunk in response.content:
        try:
            chunk_str = raw_chunk.decode("utf-8", errors="ignore")
        except Exception:
            continue
        buffer += chunk_str

        # Process complete lines
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.rstrip("\r")

            if not line.startswith("data: "):
                continue

            json_str = line[6:].strip()
            if not json_str or json_str == "[DONE]":
                continue

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                log.warning(f"[CG] Transform: JSON parse failed: {json_str[:200]}")
                continue

            evt_type = data.get("type", "")

            # Text content delta
            if evt_type == "response.output_text.delta":
                delta: dict = {}
                if not sent_role:
                    delta["role"] = "assistant"
                    sent_role = True
                delta["content"] = data.get("delta", "")
                cc = _build_cc_chunk(chunk_id, created, model_id, delta)
                yield f"data: {json.dumps(cc)}\n\n".encode()
                any_yielded = True

                # Track content
                prev = content_data.get("output_text", "")
                content_data["output_text"] = prev + data.get("delta", "")

            # Function call added
            elif evt_type == "response.output_item.added":
                item = data.get("item") or {}
                if item.get("type") == "function_call":
                    tool_call_index += 1
                    tc_delta: dict = {
                        "tool_calls": [
                            {
                                "index": tool_call_index,
                                "id": item.get("call_id", ""),
                                "type": "function",
                                "function": {
                                    "name": item.get("name", ""),
                                    "arguments": "",
                                },
                            }
                        ]
                    }
                    if not sent_role:
                        tc_delta["role"] = "assistant"
                        sent_role = True
                    cc = _build_cc_chunk(chunk_id, created, model_id, tc_delta)
                    yield f"data: {json.dumps(cc)}\n\n".encode()
                    any_yielded = True

            # Function call arguments delta
            elif evt_type == "response.function_call_arguments.delta":
                if tool_call_index >= 0:
                    args_delta = data.get("delta", "")
                    tc_delta = {
                        "tool_calls": [
                            {
                                "index": tool_call_index,
                                "function": {"arguments": args_delta},
                            }
                        ]
                    }
                    cc = _build_cc_chunk(chunk_id, created, model_id, tc_delta)
                    yield f"data: {json.dumps(cc)}\n\n".encode()
                    any_yielded = True

            # Response failed — forward error to client
            elif evt_type == "response.failed":
                log.error(
                    f"[CG] Transform: response.failed raw data: {json.dumps(data, ensure_ascii=False, default=str)[:2000]}, model={model_id}"
                )
                resp = data.get("response") or {}
                error = resp.get("error") or {}
                err_msg = error.get("message", "Unknown upstream error")
                err_code = error.get("code", "")
                log.error(
                    f"[CG] Transform: Upstream response.failed: "
                    f"code={err_code}, message={err_msg}, "
                    f"status={resp.get('status', '')}, model={model_id}"
                )
                content_data["error"] = err_msg
                # Forward error as SSE error event for client
                error_cc = _build_cc_chunk(
                    chunk_id,
                    created,
                    model_id,
                    {"role": "assistant", "content": f"[Error] {err_msg}"},
                    finish_reason="stop",
                )
                yield f"data: {json.dumps(error_cc)}\n\n".encode()
                yield b"data: [DONE]\n\n"
                any_yielded = True
                return

            # Standalone error event (e.g. invalid_parameter)
            elif evt_type == "error":
                error_obj = data.get("error") or {}
                err_msg = error_obj.get("message", "Unknown error")
                err_code = error_obj.get("code", "")
                log.error(
                    f"[CG] Transform: Upstream error event: "
                    f"code={err_code}, message={err_msg}, model={model_id}"
                )
                content_data["error"] = err_msg
                error_cc = _build_cc_chunk(
                    chunk_id,
                    created,
                    model_id,
                    {"role": "assistant", "content": f"[Error] {err_msg}"},
                    finish_reason="stop",
                )
                yield f"data: {json.dumps(error_cc)}\n\n".encode()
                yield b"data: [DONE]\n\n"
                any_yielded = True
                return

            # Response incomplete
            elif evt_type == "response.incomplete":
                resp = data.get("response") or {}
                reason = (resp.get("incomplete_details") or {}).get("reason", "")
                log.warning(
                    f"[CG] Transform: response.incomplete: "
                    f"reason={reason}, model={model_id}"
                )

            # Response completed — final chunk + usage
            elif evt_type == "response.completed":
                resp = data.get("response") or {}
                if resp.get("usage"):
                    usage_data.update(resp["usage"])

                finish = "tool_calls" if tool_call_index >= 0 else "stop"
                content_data["finish_reason"] = finish

                # Extract output for logging
                for item in resp.get("output") or []:
                    if item.get("type") == "message":
                        for part in item.get("content") or []:
                            if part.get("type") == "output_text":
                                content_data["output_text"] = part.get("text", "")
                    elif item.get("type") == "function_call":
                        content_data.setdefault("tool_calls", []).append(
                            {
                                "name": item.get("name", ""),
                                "call_id": item.get("call_id", ""),
                                "arguments": item.get("arguments", ""),
                            }
                        )

                cc = _build_cc_chunk(
                    chunk_id, created, model_id, {}, finish_reason=finish
                )
                yield f"data: {json.dumps(cc)}\n\n".encode()
                yield b"data: [DONE]\n\n"
                any_yielded = True

    # If no data was yielded, log for diagnostics
    if not any_yielded:
        log.error(
            f"[CG] Transform: Empty stream — no events yielded. "
            f"model={model_id}, upstream_status={response.status}"
        )


####################################
#
# Proxy execution
#
####################################


async def _stream_proxy(
    upstream_url: str,
    method: str,
    headers: dict,
    body: Optional[bytes],
    ptype: str,
    user_id: str,
    model_id: str,
    provider_id: str,
    request: Request,
    request_summary: Optional[dict] = None,
    transform_to_completions: bool = False,
) -> StreamingResponse:
    timeout = aiohttp.ClientTimeout(
        total=AIOHTTP_CLIENT_TIMEOUT if AIOHTTP_CLIENT_TIMEOUT else 300
    )
    session = aiohttp.ClientSession(timeout=timeout)

    try:
        response = await session.request(
            method, upstream_url, headers=headers, data=body
        )
    except aiohttp.ClientError as e:
        await session.close()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream request failed: {str(e)}",
        )

    content_type = response.headers.get("content-type", "text/event-stream")

    if response.status != 200:
        log.warning(
            f"[CG] Upstream non-200: status={response.status}, "
            f"model={model_id}, url={upstream_url}"
        )

    # Shared mutable state — generator populates, background task records
    usage_data: dict = {}
    content_data: dict = {}

    async def generate():
        try:
            if transform_to_completions and response.status == 200:
                async for chunk in _transform_responses_stream(
                    response, model_id, usage_data, content_data
                ):
                    yield chunk
            else:
                async for chunk in response.content:
                    yield chunk
                    try:
                        chunk_str = chunk.decode("utf-8", errors="ignore")
                        _update_stream_data(ptype, chunk_str, usage_data, content_data)
                    except Exception:
                        pass
        except Exception as e:
            log.error(f"[CG] Stream error: {e}")
        finally:
            response.close()
            await session.close()

    def _record_stream_usage():
        if ptype == "anthropic" and usage_data:
            total = usage_data.get("input_tokens", 0) + usage_data.get(
                "output_tokens", 0
            )
            usage_data["total_tokens"] = total

        final_content = _finalize_content_data(content_data)
        _client = getattr(request.state, "client_type", "unknown")
        enriched = _build_enriched_usage(
            usage_data, provider_id, request_summary, final_content, client_type=_client
        )
        _record_usage(
            user_id,
            model_id,
            enriched,
            provider_id,
            tool_calls=final_content.get("tool_calls"),
        )

    from starlette.background import BackgroundTask

    return StreamingResponse(
        generate(),
        media_type=content_type,
        status_code=response.status,
        headers={
            k: v for k, v in response.headers.items() if k.lower() not in _HOP_HEADERS
        },
        background=BackgroundTask(_record_stream_usage),
    )


async def _non_stream_proxy(
    upstream_url: str,
    method: str,
    headers: dict,
    body: Optional[bytes],
    ptype: str,
    user_id: str,
    model_id: str,
    provider_id: str,
    request_summary: Optional[dict] = None,
    request: Optional[Request] = None,
) -> JSONResponse:
    timeout = aiohttp.ClientTimeout(
        total=AIOHTTP_CLIENT_TIMEOUT if AIOHTTP_CLIENT_TIMEOUT else 300
    )
    session = aiohttp.ClientSession(timeout=timeout)

    try:
        response = await session.request(
            method, upstream_url, headers=headers, data=body
        )
        response_body = await response.read()
        resp_status = response.status
        resp_headers = {
            k: v for k, v in response.headers.items() if k.lower() not in _HOP_HEADERS
        }
        response.close()
        await session.close()

    except aiohttp.ClientError as e:
        await session.close()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Upstream request failed: {str(e)}",
        )

    # Record usage
    try:
        resp_json = json.loads(response_body) if response_body else {}
        usage_data = _extract_response_usage(ptype, resp_json)
        content = _extract_response_content(ptype, resp_json)
        _client = (
            getattr(request.state, "client_type", "unknown") if request else "unknown"
        )
        enriched = _build_enriched_usage(
            usage_data or {}, provider_id, request_summary, content, client_type=_client
        )
        _record_usage(
            user_id,
            model_id,
            enriched,
            provider_id,
            tool_calls=content.get("tool_calls"),
        )
    except Exception as e:
        log.error(f"Failed to extract non-stream usage: {e}")
        resp_json = {}

    # Apply output guardrails to response content
    if request and resp_status == 200 and resp_json:
        try:
            resp_text = content.get("output_text", "") if content else ""
            if resp_text:
                processed, blocked = await _apply_guardrails_to_response(
                    request,
                    resp_text,
                    user_id=user_id,
                    model_id=model_id,
                    provider_id=provider_id,
                )
                if blocked:
                    return JSONResponse(
                        content={
                            "error": {
                                "message": f"Guardrail blocked: {processed}",
                                "type": "guardrail_blocked",
                            }
                        },
                        status_code=451,
                        headers=resp_headers,
                    )
                if processed != resp_text:
                    # Replace content in response JSON
                    _replace_response_content(ptype, resp_json, processed)
        except Exception as e:
            log.error(f"[CG] Output guardrail error: {e}")

    return JSONResponse(
        content=resp_json,
        status_code=resp_status,
        headers=resp_headers,
    )


async def _proxy_models_endpoint(
    request: Request, provider_config: dict, ptype: str
) -> JSONResponse:
    """Proxy /models endpoint with allowed_models filtering."""
    api_url = provider_config["api_url"].rstrip("/")

    if ptype == "azure_openai":
        # Azure: models endpoint is at the resource level
        # Strip deployment path to get resource-level URL
        parts = api_url.split("/openai/")
        resource_url = parts[0] if len(parts) > 1 else api_url
        api_version = provider_config.get("api_version", "2024-12-01-preview")
        upstream_url = f"{resource_url}/openai/models?api-version={api_version}"
        auth_headers = {"api-key": provider_config["api_key"]}
    else:
        upstream_url = f"{api_url}/models"
        auth_headers = {"Authorization": f"Bearer {provider_config['api_key']}"}

    timeout = aiohttp.ClientTimeout(total=30)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(upstream_url, headers=auth_headers) as resp:
                data = await resp.json()
    except Exception:
        return JSONResponse(content={"data": []})

    allowed = request.app.state.config.CODE_GATEWAY_ALLOWED_MODELS
    if allowed and "data" in data:
        data["data"] = [m for m in data["data"] if m.get("id") in allowed]

    return JSONResponse(content=data)
