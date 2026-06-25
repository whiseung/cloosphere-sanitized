# Cloosphere Teams App (P2 sideload)

Teams 데스크톱/웹에 sideload 할 custom app 패키지.

## 파일 구성

- `manifest.json` — Teams app 매니페스트 (`{{BOT_APP_ID}}` 플레이스홀더 포함)
- `color.png` — 192x192 Cloosphere 로고 (Teams 앱 갤러리용)
- `outline.png` — 32x32 흰색 실루엣 (Teams 상단 탭바용)
- `pack.sh` — 플레이스홀더 치환 + zip 생성 스크립트

## 빌드

```bash
BOT_APP_ID=<Azure Bot App ID (GUID)> bash pack.sh
# → manifest.zip 생성됨
```

## Teams 에 업로드

1. Teams 왼쪽 앱 아이콘 → "Manage your apps" → "Upload an app"
   (관리자 동의 필요한 경우: Teams 관리센터 → "Integrated apps" → "Upload custom app")
2. `manifest.zip` 선택
3. "Add" → 봇 대화 시작
