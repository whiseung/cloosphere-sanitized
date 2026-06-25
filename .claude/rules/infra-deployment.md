---
paths:
  - "Dockerfile"
  - "docker-compose.yaml"
  - "docker-compose*.yml"
  - "Makefile"
  - "backend/start.sh"
  - "backend/dev.sh"
---

# Docker/DevOps 배포 규칙

## Dockerfile (멀티 스테이지)
1. **빌드 스테이지**: Node.js → `npm run build` (프론트엔드)
2. **런타임 스테이지**: Python → 빌드 결과 복사 + 백엔드 설치
3. Build args: `USE_CUDA`, `USE_OLLAMA`, `USE_EMBEDDING_MODEL`
4. 최종 이미지: `backend/start.sh` 실행

## Docker Compose
- `ollama`: Ollama 서버 (GPU 지원)
- `open-webui`: 메인 앱 (Ollama 의존)
- 볼륨: ollama 데이터, open-webui 데이터
- 환경 변수로 설정 주입

## Makefile 명령어
- `make install`: docker compose up -d
- `make start`: docker compose start
- `make stop`: docker compose stop
- `make update`: git pull + docker compose 재빌드
- `make remove`: docker compose down (확인 프롬프트)

## 개발 서버
- `backend/dev.sh`: uvicorn --reload (핫 리로드)
- `backend/start.sh`: uvicorn 프로덕션 실행
- 프론트엔드: `npm run dev` (Vite HMR, port 5173)
- 백엔드: port 8080

## 참조 파일
- `Dockerfile`: 멀티 스테이지 빌드
- `docker-compose.yaml`: 서비스 구성
- `Makefile`: 편의 명령어
- `backend/start.sh`, `backend/dev.sh`: 서버 실행
