# Cloosphere Monitoring Stack

Prometheus + Grafana 기반 모니터링 환경.

## 아키텍처

```
┌─────────────────┐      OTLP push       ┌──────────────┐    scrape    ┌────────────┐
│  Cloosphere App  │ ──────────────────► │ OTEL Collector │ ◄───────── │ Prometheus │
│  (N instances)   │   gRPC :4317        │   :8889       │            │   :9090    │
└─────────────────┘   HTTP  :4318        └──────────────┘            └─────┬──────┘
                                                                           │
                      ┌──────────────┐                               ┌─────▼──────┐
                      │ Node Exporter │ ◄─────────────────────────── │  Grafana   │
                      │   :9100       │   scrape                     │   :3000    │
                      ├──────────────┤                               └────────────┘
                      │ PG Exporter  │
                      │   :9187       │
                      ├──────────────┤
                      │ Redis Export │
                      │   :9121       │
                      └──────────────┘
```

- **앱 메트릭**: OTEL push 방식 (scale-out 대응, 인스턴스 수 무관)
- **시스템 메트릭**: Node Exporter (CPU, 메모리, 디스크, 네트워크)
- **DB 메트릭**: PostgreSQL Exporter, Redis Exporter

## 사전 설정

### 1. 환경 변수 (.env)

`.env.example`을 복사하여 `.env` 파일을 생성합니다.

```bash
cp .env.example .env
```

`.env` 파일을 편집하여 실제 값을 입력합니다:

```env
# Grafana 관리자 계정
GF_ADMIN_USER=admin
GF_ADMIN_PASSWORD=<원하는 비밀번호>

# PostgreSQL Exporter 접속 정보
POSTGRES_DATA_SOURCE=postgresql://<user>:<password>@<db-host>:5432/<dbname>?sslmode=disable

# Redis Exporter 접속 정보 (Azure Redis Cache)
REDIS_ADDR=rediss://<redis-host>.redis.cache.windows.net:6380
REDIS_PASSWORD=<redis-access-key>
```

> **참고**: Azure Redis Cache는 TLS(rediss://) + 포트 6380을 사용합니다.

### 2. 데이터 디렉토리 생성

```bash
mkdir -p data/prometheus data/grafana
chown -R 65534:65534 data/prometheus   # Prometheus (nobody)
chown -R 472:472 data/grafana          # Grafana
```

### 3. 앱 서버 환경 변수 (Cloosphere)

앱 메트릭을 수집하려면 Cloosphere 앱 서버에 다음 환경 변수를 설정합니다:

```env
ENABLE_OTEL=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://<monitor-host>:4317
```

> scale-out 환경에서는 모든 인스턴스에 동일하게 설정합니다.

## 실행

```bash
# 시작
docker compose up -d

# 상태 확인
docker compose ps

# 로그 확인
docker compose logs -f <service-name>

# 중지
docker compose down
```

## 접속

| 서비스 | URL | 기본 계정 |
|--------|-----|-----------|
| Grafana | http://localhost:3000 | .env에서 설정 |
| Prometheus | http://localhost:9090 | - |

## 프리셋 대시보드

Grafana 시작 시 자동으로 로드됩니다:

| 대시보드 | 설명 |
|----------|------|
| Node Exporter Full | CPU, 메모리, 디스크, 네트워크 (ID: 15172) |
| PostgreSQL Database | 연결 수, 트랜잭션, 캐시 히트율 (ID: 9628) |
| Redis Dashboard | 메모리, 명령 수, 연결 수 (ID: 763) |

## 데이터 보존

- **Prometheus**: 30일 (`--storage.tsdb.retention.time=30d`)
- **데이터 위치**: `./data/prometheus/`, `./data/grafana/`

## 파일 구조

```
monitor/
├── docker-compose.yml          # 서비스 정의
├── prometheus.yml               # Prometheus 수집 설정
├── otel-collector.yml           # OTEL Collector 설정
├── .env.example                 # 환경 변수 템플릿
├── .env                         # 실제 환경 변수 (gitignore)
├── data/                        # 데이터 디렉토리 (gitignore)
│   ├── prometheus/
│   └── grafana/
└── grafana/
    └── provisioning/
        ├── datasources/
        │   └── prometheus.yml   # 데이터소스 자동 설정
        └── dashboards/
            ├── dashboards.yml   # 대시보드 프로바이더 설정
            ├── node-exporter.json
            ├── postgresql.json
            └── redis.json
```
