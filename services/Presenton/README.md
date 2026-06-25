# PPT Generator (powered by Presenton) — 독립 서비스

> Cloosphere 마켓플레이스(관리자 > 설정 > 마켓플레이스)에는 **"PPT Generator"** 로 표시된다.
> 내부 구현은 오픈소스 Presenton 을 래핑한 것이며, config 키(`PRESENTON_*`)·도구 코드는 그대로 유지된다.

[Presenton](https://github.com/presenton/presenton) — 오픈소스 AI 프레젠테이션 생성기(Apache 2.0).
**편집 가능한 PPTX/PDF** 를 생성하고, **내장 MCP 서버**를 제공한다.

이 폴더는 Presenton 을 **Cloosphere 와 완전히 별개**로 띄우는 배포 스크립트다.
Cloosphere 는 코드 변경 없이, 관리자의 **Tool Connections(MCP)** 로 이 서비스에 연결해서 사용한다.

```
┌─ Cloosphere (별개) ─┐        MCP(HTTP)        ┌─ 이 폴더가 띄우는 Presenton ─┐
│ UnifiedAgent        │ ───────────────────────▶│ /mcp   (내장 MCP 서버 :8001)  │
│  └ Tool Connections │                          │ /api/v1 (REST :8000)          │
│     (MCP 커넥션)     │ ◀── 다운로드 링크 텍스트 ─│ /app_data/exports/*.pptx      │
└─────────────────────┘                          │ LLM/이미지 = Presenton 자체키 │
                                                  └───────────────────────────────┘
```

---

## 1. 실행

> ⚠️ 이미지가 **GB급**(Chromium + LibreOffice + Tesseract + Node + Python). 최초 pull 에 수 분.

```bash
cd services/Presenton
cp .env.example .env          # 그리고 LLM 키 등 채우기 (최소 OPENAI_API_KEY)
make up                       # = docker compose up -d
make logs                     # 기동 로그
make health                   # API 응답 확인
```

기동되면:
- 웹 UI: `http://localhost:5001`
- REST:  `http://localhost:5001/api/v1/...`
- MCP:   `http://localhost:5001/mcp`

`.env` 의 핵심 스위치:
- `DISABLE_AUTH=true` — MCP/REST 무인증 + 생성물 공개 다운로드. (내부망 전제)
- `LLM` + 키 — Presenton **자체 키**로 LLM 호출.
- `NEXT_PUBLIC_URL` — 외부에서 접근하는 공개 주소(다운로드 링크 베이스).
- `DISABLE_IMAGE_GENERATION=true` — 처음엔 끄고 텍스트 슬라이드부터 검증 권장.

---

## 2. Cloosphere 에 연결 (코드 변경 0)

1. `make mcp-url` 로 MCP URL 확인.
2. Cloosphere **관리자 → Tool Connections** → MCP 서버 추가:
   - URL: `http://<presenton-host>:5001/mcp`
     - Cloosphere 가 **docker 안**이면 `localhost` 대신 `host.docker.internal` 또는 호스트 IP.
   - 인증: **none** (`DISABLE_AUTH=true` 이므로)
   - **timeout: `180`** (필수) — 생성이 ~60s+ 걸려 기본 30s 로는 끊긴다. 연결 설정 JSON 의
     `data.connection.timeout` 에 180 을 넣을 것. (Cloosphere `mcp_client` 가 이 값을 읽음)
3. 에이전트에 이 Tool Connection 을 연결.
4. 사용: 에이전트가 Presenton 의 `generate` 도구를 호출 → 응답에 생성된 파일 경로(`path`)가 포함됨.
   - 다운로드 URL = `NEXT_PUBLIC_URL` + `path` (예: `http://localhost:5001/app_data/exports/<id>.pptx`).

### 다운로드 링크를 답변에 확실히 넣으려면 (선택, 코드 아님)
generic MCP 결과는 에이전트의 최종답변 **컨텍스트로만** 들어가므로, 에이전트가 링크를
빼먹지 않게 **작업(task) 프롬프트**에 한 줄 넣어두면 안정적이다:

> 프레젠테이션을 생성하면 반드시 다운로드 링크를 `NEXT_PUBLIC_URL + path` 형태의 마크다운
> 링크로 답변에 포함하라. (예: `[발표자료.pptx](http://localhost:5001/app_data/exports/...)`)

---

## 3. 알아둘 제약 (설계상 트레이드오프)

- **연결 방식**: Cloosphere 백엔드의 in-process 도구(`create_presentation`)가 Presenton REST 를
  호출 → 결과를 **Cloosphere Files 에 ingest** → 채팅 네이티브 다운로드 칩. 따라서 Presenton 은
  **Cloosphere 백엔드에서만 닿으면 되고**(서버↔서버), 사용자 브라우저에 노출할 필요 없다.
  (이전 MCP Tool Connections 방식은 폐기 — 관리자>설정>문서템플릿의 Presenton 섹션 + `PRESENTON_*` config 로 연결)
- `DISABLE_AUTH=true` 는 **무인증** → 반드시 내부망/리버스프록시 뒤에 둘 것.
- 생성은 멀티 LLM + 렌더 + (이미지 켜면) 슬라이드당 이미지라 수십초~수분. 타임아웃은
  Cloosphere `PRESENTON_TIMEOUT`(관리 UI) 로 조절. 도구가 비동기 폴링으로 단계별 진행상황을 표시한다.
- **토큰 사용량 추적**: 기본(자체 키)은 Presenton LLM 토큰이 Cloosphere 에 안 잡힌다. 잡으려면
  `.env` 에서 `LLM=custom` + `CUSTOM_LLM_URL=http://host.docker.internal:8080/openai/v1` +
  Cloosphere **서비스 계정 API 키**로 라우팅 (.env.example D-1 참조). → usage 에
  `message_type=external_service` 로 기록(쿼터 미차감). 이미지 토큰은 여전히 미집계.
- 실 LLM 검증은 유효한 키가 필요하다(이 레포의 테스트 인스턴스가 아니라 **실 키가 있는 환경**에서).

---

## 4. 명령어

```bash
make help      # 목록
make up        # 기동
make down      # 중지(+제거, app_data 는 보존)
make restart   # 재기동
make logs      # 로그 follow
make ps        # 상태/health
make pull      # 최신 이미지
make mcp-url   # MCP 연결 URL 출력
```

데이터를 완전히 지우려면 `make down` 후 `app_data/` 디렉터리를 삭제.
