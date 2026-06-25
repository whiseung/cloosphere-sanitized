import io
import logging
import tarfile
from pathlib import Path
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MONITORING_STATIC_DIR = Path(__file__).parent.parent / "static" / "monitoring"

DOCKER_COMPOSE_CORE = """\
services:
  ##################################################
  # 모니터링 코어
  ##################################################

  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    restart: unless-stopped
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - ./data/prometheus:/prometheus
    ports:
      - "9090:9090"
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=30d"

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    restart: unless-stopped
    volumes:
      - ./data/grafana:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning
    ports:
      - "3000:3000"
    user: "472"
    environment:
      - GF_SECURITY_ADMIN_USER=${GF_ADMIN_USER:-admin}
      - GF_SECURITY_ADMIN_PASSWORD=${GF_ADMIN_PASSWORD:-admin}
      - GF_SERVER_ROOT_URL=http://localhost:3000

  ##################################################
  # 로그 저장 (Loki)
  # OTEL Collector에서 앱 로그를 수신하여 Grafana에서 조회
  ##################################################

  loki:
    image: grafana/loki:latest
    container_name: loki
    restart: unless-stopped
    volumes:
      - ./data/loki:/loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml

  ##################################################
  # OTEL Collector
  # 앱의 traces/metrics를 수집하여 Prometheus에 노출
  # 앱에 ENABLE_OTEL=true, OTEL_EXPORTER_OTLP_ENDPOINT 설정 필요
  ##################################################

  otel-collector:
    image: otel/opentelemetry-collector-contrib:latest
    container_name: otel-collector
    restart: unless-stopped
    volumes:
      - ./otel-collector.yml:/etc/otelcol-contrib/config.yaml
    ports:
      - "4317:4317"   # OTLP gRPC (앱→Collector)
      - "4318:4318"   # OTLP HTTP
      - "8889:8889"   # Prometheus exporter (Collector→Prometheus)

"""

DOCKER_COMPOSE_POSTGRES = """
  ##################################################
  # PostgreSQL 모니터링
  ##################################################

  postgres-exporter:
    image: prometheuscommunity/postgres-exporter:latest
    container_name: postgres-exporter
    restart: unless-stopped
    environment:
      DATA_SOURCE_NAME: ${POSTGRES_DATA_SOURCE}
    ports:
      - "9187:9187"
"""

DOCKER_COMPOSE_REDIS = """
  ##################################################
  # Redis 모니터링
  ##################################################

  redis-exporter:
    image: oliver006/redis_exporter:latest
    container_name: redis-exporter
    restart: unless-stopped
    environment:
      REDIS_ADDR: ${REDIS_ADDR}
      REDIS_PASSWORD: ${REDIS_PASSWORD}
      REDIS_EXPORTER_SKIP_TLS_VERIFICATION: "true"
    ports:
      - "9121:9121"
"""

PROMETHEUS_YML_CORE = """\
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Cloosphere 앱 메트릭 (OTEL Collector 경유)
  - job_name: "otel-collector"
    static_configs:
      - targets: ["otel-collector:8889"]
"""

PROMETHEUS_YML_POSTGRES = """
  # PostgreSQL
  - job_name: "postgresql"
    static_configs:
      - targets: ["postgres-exporter:9187"]
"""

PROMETHEUS_YML_REDIS = """
  # Redis
  - job_name: "redis"
    static_configs:
      - targets: ["redis-exporter:9121"]
"""

OTEL_COLLECTOR_YML = """\
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

exporters:
  prometheus:
    endpoint: 0.0.0.0:8889
    resource_to_telemetry_conversion:
      enabled: true
  otlp_http/loki:
    endpoint: http://loki:3100/otlp
  debug:
    verbosity: basic

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus]
    traces:
      receivers: [otlp]
      exporters: [debug]
    logs:
      receivers: [otlp]
      exporters: [otlp_http/loki]
"""


ENV_EXAMPLE = """\
# Grafana
GF_ADMIN_USER=admin
GF_ADMIN_PASSWORD=admin

# PostgreSQL Exporter
POSTGRES_DATA_SOURCE=postgresql://<user>:<password>@<db-host>:5432/<dbname>?sslmode=require

# Redis Exporter (Azure Redis Cache)
# rediss:// = TLS, 포트 6380
REDIS_ADDR=rediss://<redis-host>.redis.cache.windows.net:6380
REDIS_PASSWORD=<redis-access-key>
"""

SETUP_SH = """\
#!/bin/bash
set -e

echo "=== Cloosphere Monitoring Setup ==="

# ──────────────────────────────────────
# 1. Docker 설치 확인
# ──────────────────────────────────────
if ! command -v docker &> /dev/null; then
    echo ""
    echo "[*] Docker가 설치되어 있지 않습니다. 설치를 시작합니다..."
    curl -fsSL https://get.docker.com | sh
    sudo systemctl enable docker
    sudo systemctl start docker
    echo "[✓] Docker 설치 완료"
fi

# Docker Compose 확인 (docker compose v2 플러그인)
if ! docker compose version &> /dev/null; then
    echo ""
    echo "[*] Docker Compose 플러그인을 설치합니다..."
    # 공식 apt 패키지 시도, 실패 시 바이너리 직접 설치
    if sudo apt-get update -qq && sudo apt-get install -y -qq docker-compose-plugin 2>/dev/null; then
        echo "[✓] Docker Compose 설치 완료 (apt)"
    else
        echo "[*] apt 설치 실패, 바이너리를 직접 다운로드합니다..."
        COMPOSE_VERSION=$(curl -fsSL https://api.github.com/repos/docker/compose/releases/latest | grep tag_name | cut -d '"' -f 4)
        sudo mkdir -p /usr/local/lib/docker/cli-plugins
        sudo curl -fsSL "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" \
            -o /usr/local/lib/docker/cli-plugins/docker-compose
        sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
        echo "[✓] Docker Compose ${COMPOSE_VERSION} 설치 완료 (binary)"
    fi
fi

echo "[✓] Docker $(docker --version | awk '{print $3}' | tr -d ',')"
echo "[✓] Docker Compose $(docker compose version --short)"

# ──────────────────────────────────────
# 2. 기존 서비스 충돌 감지
# ──────────────────────────────────────
echo ""
CONFLICT=false

check_container() {
    local name="$1"
    local port="$2"
    local label="$3"

    # 같은 이름의 컨테이너 확인
    if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx "$name"; then
        echo "[!] 기존 컨테이너 감지: $name ($label)"
        CONFLICT=true
        return
    fi

    # 포트 사용 확인
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
       netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        echo "[!] 포트 충돌 감지: $port ($label)"
        CONFLICT=true
    fi
}

check_container "grafana"        3000 "Grafana"
check_container "prometheus"     9090 "Prometheus"
check_container "loki"           3100 "Loki"
check_container "otel-collector" 4317 "OTEL Collector"

if [ "$CONFLICT" = true ]; then
    echo ""
    echo "──────────────────────────────────────────────────"
    echo "  기존 모니터링 서비스가 감지되었습니다."
    echo ""
    echo "  [업그레이드] 이전 Cloosphere 번들로 설치한 경우:"
    echo "    기존 디렉토리에서 docker compose down 후"
    echo "    이 디렉토리에서 다시 실행하세요."
    echo ""
    echo "  [공존] 별도 Grafana/Prometheus를 운영 중인 경우:"
    echo "    docker-compose.yml에서 포트를 변경하거나,"
    echo "    기존 Grafana에 Loki datasource를 수동 추가하세요."
    echo "    (Loki URL: http://loki:3100)"
    echo "──────────────────────────────────────────────────"
    echo ""
    read -p "그래도 계속 진행하시겠습니까? (y/N) " -r
    if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
        echo "설치를 취소합니다."
        exit 0
    fi
    echo ""
fi

# ──────────────────────────────────────
# 3. 데이터 디렉토리 및 권한
# ──────────────────────────────────────
mkdir -p data/prometheus data/grafana data/loki
sudo chown -R 65534:65534 data/prometheus  # Prometheus (nobody)
sudo chown -R 472:472 data/grafana          # Grafana
sudo chown -R 10001:10001 data/loki         # Loki

# ──────────────────────────────────────
# 4. .env 파일 확인
# ──────────────────────────────────────
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "[!] .env 파일이 생성되었습니다."
    echo "    .env 파일을 편집하여 DB/Redis 접속 정보를 입력하세요."
    echo "    편집 후 다시 이 스크립트를 실행하세요."
    exit 0
fi

# ──────────────────────────────────────
# 5. Docker Compose 실행
# ──────────────────────────────────────
echo ""
echo "Docker Compose 시작..."
docker compose up -d

echo ""
echo "=== 설정 완료 ==="
echo "Grafana:    http://localhost:3000"
echo "Prometheus: http://localhost:9090"
echo "Loki:       http://localhost:3100"
echo ""
echo "Grafana 대시보드:"
echo "  - Cloosphere App:  http://localhost:3000/d/cloosphere-app"
echo "  - Error Logs:      http://localhost:3000/d/cloosphere-error-logs"
echo "  - Process Runtime: http://localhost:3000/d/cloosphere-process"
echo ""
echo "=== OTEL Endpoint 설정 ==="
echo "Cloosphere 관리자 > Settings > Monitoring에서 OTEL을 활성화하고"
echo "아래 중 환경에 맞는 엔드포인트를 입력하세요:"
echo ""
echo "  HTTP (권장, Azure App Service 등 클라우드 환경):"
echo "    http://<이 서버 IP>:4318"
echo ""
echo "  gRPC (Docker/VM에서 직접 실행하는 경우):"
echo "    http://<이 서버 IP>:4317"
"""


def _parse_database_url(database_url: str) -> str | None:
    """DATABASE_URL(SQLAlchemy)을 PostgreSQL exporter용 DSN으로 변환"""
    if not database_url or "sqlite" in database_url:
        return None
    # postgresql+psycopg2:// → postgresql://
    dsn = database_url.split("?")[0]
    query = database_url.split("?")[1] if "?" in database_url else ""
    for prefix in ("postgresql+psycopg2://", "postgresql+asyncpg://", "postgres://"):
        if dsn.startswith(prefix):
            dsn = "postgresql://" + dsn[len(prefix) :]
            break
    if query:
        # postgres-exporter는 sslmode=prefer 미지원 → require로 변환
        query = query.replace("sslmode=prefer", "sslmode=require")
        dsn = f"{dsn}?{query}"
    return dsn


def _parse_redis_url(redis_url: str) -> tuple[str, str] | None:
    """REDIS_URL에서 (addr, password)를 추출"""
    if not redis_url:
        return None
    try:
        parsed = urlparse(redis_url)
        scheme = parsed.scheme or "redis"
        host = parsed.hostname or "localhost"
        port = parsed.port or (6380 if scheme == "rediss" else 6379)
        addr = f"{scheme}://{host}:{port}"
        password = parsed.password or ""
        return addr, password
    except Exception:
        log.warning(f"Failed to parse REDIS_URL: {redis_url}")
        return None


def _build_env(
    postgres_dsn: str | None,
    redis_info: tuple[str, str] | None,
) -> str:
    """서버 설정 기반으로 .env 파일 내용을 생성"""
    lines = [
        "# Grafana",
        "GF_ADMIN_USER=admin",
        "GF_ADMIN_PASSWORD=admin",
    ]
    if postgres_dsn:
        lines += [
            "",
            "# PostgreSQL Exporter",
            f"POSTGRES_DATA_SOURCE={postgres_dsn}",
        ]
    if redis_info:
        addr, password = redis_info
        lines += [
            "",
            "# Redis Exporter",
            f"REDIS_ADDR={addr}",
            f"REDIS_PASSWORD={password}",
        ]
    return "\n".join(lines) + "\n"


def _add_bytes_to_tar(tf: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644):
    """tar에 바이트 데이터를 파일로 추가"""
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    info.mode = mode
    tf.addfile(info, io.BytesIO(data))


def generate_monitoring_bundle(
    database_url: str = "",
    redis_url: str = "",
) -> bytes:
    """모니터링 설정 파일들을 tar.gz로 패키징 (서버 설정 기반 자동 구성)"""
    postgres_dsn = _parse_database_url(database_url)
    redis_info = _parse_redis_url(redis_url)

    has_postgres = postgres_dsn is not None
    has_redis = redis_info is not None

    # docker-compose.yml 동적 생성
    compose = DOCKER_COMPOSE_CORE
    if has_postgres:
        compose += DOCKER_COMPOSE_POSTGRES
    if has_redis:
        compose += DOCKER_COMPOSE_REDIS

    # prometheus.yml 동적 생성
    prometheus = PROMETHEUS_YML_CORE
    if has_postgres:
        prometheus += PROMETHEUS_YML_POSTGRES
    if has_redis:
        prometheus += PROMETHEUS_YML_REDIS

    # .env 자동 생성
    env_content = _build_env(postgres_dsn, redis_info)

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        prefix = "cloosphere-monitor"

        _add_bytes_to_tar(tf, f"{prefix}/docker-compose.yml", compose.encode())
        _add_bytes_to_tar(tf, f"{prefix}/prometheus.yml", prometheus.encode())
        _add_bytes_to_tar(
            tf, f"{prefix}/otel-collector.yml", OTEL_COLLECTOR_YML.encode()
        )
        _add_bytes_to_tar(tf, f"{prefix}/.env", env_content.encode())
        _add_bytes_to_tar(tf, f"{prefix}/.env.example", ENV_EXAMPLE.encode())
        _add_bytes_to_tar(tf, f"{prefix}/setup.sh", SETUP_SH.encode(), mode=0o755)

        # Grafana provisioning files from static directory
        grafana_dir = MONITORING_STATIC_DIR / "grafana" / "provisioning"
        if grafana_dir.exists():
            for file_path in grafana_dir.rglob("*"):
                if file_path.is_file():
                    rel = file_path.relative_to(MONITORING_STATIC_DIR)
                    tf.add(file_path, f"{prefix}/{rel}")

    buf.seek(0)
    return buf.getvalue()
