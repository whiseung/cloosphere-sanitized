---
paths:
  - "backend/open_webui/socket/**/*.py"
---

# Socket.IO 실시간 통신 규칙

## 서버 생성
```python
sio = socketio.AsyncServer(
    cors_allowed_origins=[],
    async_mode="asgi",
    transports=["polling", "websocket"],  # ENABLE_WEBSOCKET_SUPPORT 조건부
)
```

## 상태 풀
- `SESSION_POOL`: sid → user 매핑 (세션 관리)
- `USER_POOL`: user_id → {sid_set} 매핑 (프레젠스 추적)
- `USAGE_POOL`: model_id → {sid: {updated_at}} (모델 사용량)

## Redis 지원 (분산 배포)
- `RedisDict`: JSON 직렬화 기반 분산 딕셔너리 (socket/utils.py)
- `RedisLock`: 분산 락 메커니즘
- Redis Sentinel HA 지원

## 핵심 이벤트
- `connect`: JWT 토큰 검증 → USER_POOL 등록 → user-list emit
- `user-join`: 프레젠스 업데이트
- `usage`: 모델 사용량 추적 → USAGE_POOL 갱신
- `disconnect`: USER_POOL 정리 → user-list emit

## 연결 흐름
1. 클라이언트 JWT 토큰 전송
2. 토큰 디코드 → 유저 조회
3. SESSION_POOL에 sid→user 등록
4. USER_POOL에 user_id→sids 등록
5. user-list, usage emit

## 주기적 정리
- `periodic_usage_pool_cleanup()`: 분산 락으로 타임아웃 클린업
- 비활성 사용자 자동 제거

## 참조 파일
- `socket/main.py`: AsyncServer, 이벤트 핸들러, 풀 관리
- `socket/utils.py`: RedisDict, RedisLock
