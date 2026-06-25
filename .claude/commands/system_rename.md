# system_rename

고객사 배포 전 시스템 이름을 변경합니다.
기존 Cloosphere로 된 이름을 입력된 이름으로 변경 합니다.
한글명과 영문명을 함께 입력받습니다.

## 사용법

```
/system_rename 삼성전자, Samsung
/system_rename SK 하이닉스, SK Hynix
```

**입력 형식**: `한글명, 영문명`

## 변경 대상

| 파일 | 변경 내용 | 사용 이름 |
|------|----------|----------|
| `src/app.html` | meta 태그, title (4곳) | 영문명 |
| `.env` | `WEBUI_NAME` 값 | 한글명 |
| `src/lib/i18n/locales/en-US/translation.json` | Cloosphere 포함 번역 | 영문명 |
| `src/lib/i18n/locales/ko-KR/translation.json` | Cloosphere 포함 번역 | 한글명 |

## 작업 순서

1. **입력값 파싱**
   - 쉼표로 구분: `한글명, 영문명`
   - 없으면 사용자에게 질문

2. **app.html 변경** (영문명 사용)
   ```html
   <meta name="apple-mobile-web-app-title" content="{{영문명}}" />
   <meta name="description" content="{{영문명}}" />
   <link ... title="{{영문명}}" href="/opensearch.xml" />
   <title>{{영문명}}</title>
   ```

3. **.env 파일 변경** (한글명 사용)
   ```bash
   WEBUI_NAME={{한글명}}
   ```

4. **i18n 번역 파일 변경**

   먼저 변경 대상 검색:
   ```bash
   grep -r "Cloosphere\|Open WebUI" src/lib/i18n/locales/
   ```

   **변경할 항목** (값에서 제품명으로 사용되는 경우):
   - `"Open WebUI uses faster-whisper internally"` → `"{{이름}} uses..."`
   - `"CORS must be properly configured ... from Open WebUI"` → `"... from {{이름}}"`
   - `"Open WebUI uses SpeechT5..."` → `"{{이름}} uses SpeechT5..."`

   **변경하지 않을 항목** (외부 커뮤니티 참조):
   - `"Share to Open WebUI Community"` - 외부 커뮤니티 공유 기능
   - `"Made by Open WebUI Community"` - 원본 프로젝트 크레딧
   - `"Redirecting you to Open WebUI Community"` - 외부 링크

   **en-US**: 영문명으로 변경
   **ko-KR**: 한글명으로 변경

5. **빌드 안내**
   ```bash
   APP_NAME="{{영문명}}" npm run build
   ```

6. **로고 변경 안내**

   로고/파비콘은 수동 교체 필요:
   ```
   static/favicon.png        - 브라우저 탭 아이콘 (32x32)
   static/splash.png         - 로딩 화면 로고
   static/apple-touch-icon.png - iOS 아이콘 (180x180)
   ```

## 변경하지 않는 항목

- i18n 번역 **키** (내부용, 값만 변경)
- 코드 내 기술 참조 (`open_webui`, `required_open_webui_version`)
- 외부 링크 (`openwebui.com`, `docs.openwebui.com`)

## 원복 방법

Git으로 원복:
```bash
git checkout src/app.html .env src/lib/i18n/
```

## 체크리스트

- [ ] 입력값 확인 (한글명, 영문명)
- [ ] `src/app.html` 4곳 변경 (영문명)
- [ ] `.env`의 `WEBUI_NAME` 변경 (한글명)
- [ ] i18n en-US: 제품명으로 사용된 "Open WebUI" → 영문명
- [ ] i18n ko-KR: 제품명으로 사용된 "Open WebUI" → 한글명
- [ ] 외부 커뮤니티 참조는 유지 확인
- [ ] 빌드 명령어 안내
- [ ] 로고 수동 교체 안내

## 참고 문서

- `docs/engineers/rebranding/README.md` - 상세 리브랜딩 가이드
