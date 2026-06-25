#!/usr/bin/env bash
# manifest.json 의 {{BOT_APP_ID}} 플레이스홀더를 env var 로 치환한 뒤
# color/outline png 와 함께 zip 으로 묶어 Teams 에 sideload 가능한 패키지를 만든다.
#
# 사용법:
#   BOT_APP_ID=<Azure Bot App ID GUID> bash pack.sh
#
# 결과: manifest.zip
set -euo pipefail

if [[ -z "${BOT_APP_ID:-}" ]]; then
  echo "ERROR: BOT_APP_ID 환경 변수 필요 (Azure Bot Service 의 App ID, GUID 형태)" >&2
  exit 1
fi

cd "$(dirname "$0")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

sed "s/{{BOT_APP_ID}}/${BOT_APP_ID}/g" manifest.json > "$work/manifest.json"
cp color.png outline.png "$work/"

rm -f manifest.zip
WORK="$work" OUT="$PWD/manifest.zip" python3 -c "
import os, zipfile
work = os.environ['WORK']
out = os.environ['OUT']
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    for name in ('manifest.json', 'color.png', 'outline.png'):
        z.write(os.path.join(work, name), arcname=name)
"

echo "manifest.zip 생성 완료 ($(stat -c%s manifest.zip) bytes)"
echo "Teams 에 sideload 하세요: https://admin.teams.microsoft.com → Integrated apps → Upload custom app"
