import logging
import os

from fastapi import FastAPI
from open_webui.env import OTEL_SERVICE_NAME
from open_webui.utils.telemetry.exporters import LazyBatchSpanProcessor
from open_webui.utils.telemetry.instrumentors import Instrumentor
from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from sqlalchemy import Engine

logger = logging.getLogger(__name__)


def _get_app_insights_connection_string(app: FastAPI) -> str:
    """Get Azure Application Insights connection string.

    Checks multiple sources in order:
    1. Admin settings (persisted in DB via PersistentConfig)
    2. APPLICATIONINSIGHTS_CONNECTION_STRING env var (Azure App Service auto-inject)
    3. APPINSIGHTS_INSTRUMENTATIONKEY env var (legacy, auto-inject)

    Returns empty string if not configured.
    """
    # 1. Admin settings
    conn_str = str(
        getattr(app.state.config, "APP_INSIGHTS_CONNECTION_STRING", "") or ""
    )
    if conn_str:
        return conn_str

    # 2. Azure App Service auto-injected env vars
    conn_str = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
    if conn_str:
        return conn_str

    # 3. Legacy instrumentation key → build connection string
    ikey = os.environ.get("APPINSIGHTS_INSTRUMENTATIONKEY", "")
    if ikey:
        return f"InstrumentationKey={ikey}"

    return ""


def setup(app: FastAPI, db_engine: Engine):
    import socket

    instance_id = os.environ.get(
        "OTEL_SERVICE_INSTANCE_ID",
        socket.gethostname(),
    )
    resource = Resource.create(
        attributes={
            SERVICE_NAME: OTEL_SERVICE_NAME,
            "service.instance.id": instance_id,
        }
    )

    # Base providers (required for instrumentors)
    trace.set_tracer_provider(TracerProvider(resource=resource))
    metric_readers = []
    log_processors = []  # Collect log processors from both OTEL and App Insights

    # OTLP exporter → OTEL Collector (for Prometheus/Grafana)
    # 환경변수 우선, 없으면 관리자 설정(DB) fallback
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "") or str(
        getattr(app.state.config, "OTEL_EXPORTER_OTLP_ENDPOINT", "") or ""
    )
    _enable_otel_env = os.environ.get("ENABLE_OTEL", "").lower()
    if _enable_otel_env:
        enable_otel = _enable_otel_env == "true"
    else:
        _enable_otel_raw = getattr(app.state.config, "ENABLE_OTEL", False)
        enable_otel = bool(
            _enable_otel_raw.value
            if hasattr(_enable_otel_raw, "value")
            else _enable_otel_raw
        )
    if enable_otel and otel_endpoint:
        try:
            # 포트 4318 또는 /v1/ 경로 → HTTP, 그 외 → gRPC
            use_http = ":4318" in otel_endpoint or "/v1/" in otel_endpoint
            if use_http:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                )
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
            else:
                from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                    OTLPMetricExporter,
                )
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                    OTLPSpanExporter,
                )

            # HTTP exporter는 endpoint를 직접 전달하면 /v1/traces 경로를 안 붙임
            # 환경변수로 설정하면 SDK가 경로를 자동 추가
            if use_http:
                os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otel_endpoint
                span_exporter = OTLPSpanExporter()
                metric_exporter = OTLPMetricExporter()
            else:
                span_exporter = OTLPSpanExporter(endpoint=otel_endpoint)
                metric_exporter = OTLPMetricExporter(endpoint=otel_endpoint)

            trace.get_tracer_provider().add_span_processor(
                LazyBatchSpanProcessor(span_exporter)
            )
            metric_readers.append(
                PeriodicExportingMetricReader(
                    metric_exporter, export_interval_millis=15000
                )
            )

            # Logs → OTEL Collector → Loki
            try:
                from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

                if use_http:
                    from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                        OTLPLogExporter,
                    )
                else:
                    from opentelemetry.exporter.otlp.proto.grpc._log_exporter import (
                        OTLPLogExporter,
                    )

                otel_log_exporter = (
                    OTLPLogExporter()
                    if use_http
                    else OTLPLogExporter(endpoint=otel_endpoint)
                )
                log_processors.append(BatchLogRecordProcessor(otel_log_exporter))
            except Exception as e:
                logger.warning(f"[Telemetry] OTLP log exporter failed: {e}")

            logger.info(f"[Telemetry] OTLP exporter enabled → {otel_endpoint}")
        except Exception as e:
            logger.error(f"[Telemetry] Failed to initialize OTLP exporter: {e}")

    # Azure Application Insights (direct SDK export)
    # Auto-instrumentation only works on "Deploy as Code" (not containers).
    # We always use our SDK — if auto-instrumentation is also active,
    # MS docs state manual SDK takes priority and auto is ignored.
    app_insights_conn = _get_app_insights_connection_string(app)
    if app_insights_conn:
        try:
            from azure.monitor.opentelemetry.exporter import (
                AzureMonitorLogExporter,
                AzureMonitorMetricExporter,
                AzureMonitorTraceExporter,
            )
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor

            # Traces → App Insights
            azure_trace_exporter = AzureMonitorTraceExporter(
                connection_string=app_insights_conn
            )
            trace.get_tracer_provider().add_span_processor(
                LazyBatchSpanProcessor(azure_trace_exporter)
            )

            # Metrics → App Insights
            azure_metric_exporter = AzureMonitorMetricExporter(
                connection_string=app_insights_conn
            )
            metric_readers.append(
                PeriodicExportingMetricReader(
                    azure_metric_exporter, export_interval_millis=60000
                )
            )

            # Logs → App Insights
            azure_log_exporter = AzureMonitorLogExporter(
                connection_string=app_insights_conn
            )
            log_processors.append(BatchLogRecordProcessor(azure_log_exporter))

            logger.info(
                "[Telemetry] Azure Application Insights enabled "
                "(traces + metrics + logs)"
            )
        except ImportError:
            logger.warning(
                "[Telemetry] azure-monitor-opentelemetry-exporter not installed, "
                "skipping App Insights integration"
            )
        except Exception as e:
            logger.error(f"[Telemetry] Failed to initialize App Insights: {e}")

    # Set up single LoggerProvider with all collected processors
    if log_processors:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler

        logger_provider = LoggerProvider(resource=resource)
        for processor in log_processors:
            logger_provider.add_log_record_processor(processor)
        set_logger_provider(logger_provider)

        # loguru sink로 OTEL에 로그 전달
        # (logging.Handler 방식은 start_logger의 force=True로 제거되므로 loguru 직접 연동)
        _otel_handler = LoggingHandler(
            level=logging.WARNING,
            logger_provider=logger_provider,
        )

        def _otel_sink(message):
            record = message.record
            level = record["level"].name
            log_level = getattr(logging, level, logging.WARNING)
            if log_level < logging.WARNING:
                return
            # 본문에 traceback 포함
            msg = record["message"]
            if record["exception"]:
                import traceback as tb

                msg += "\n" + "".join(
                    tb.format_exception(
                        type(record["exception"].value),
                        record["exception"].value,
                        record["exception"].traceback,
                    )
                )
            log_record = logging.LogRecord(
                name=record["name"] or "loguru",
                level=log_level,
                pathname=str(record["file"].path) if record["file"] else "",
                lineno=record["line"],
                msg=msg,
                args=(),
                exc_info=None,
            )
            _otel_handler.emit(log_record)

        try:
            from loguru import logger as loguru_logger

            loguru_logger.add(
                _otel_sink,
                level="WARNING",
                filter=lambda record: "auditable" not in record["extra"],
            )
        except ImportError:
            # loguru 없으면 표준 logging handler 사용
            logging.getLogger().addHandler(_otel_handler)

        logger.info(
            f"[Telemetry] Log exporter enabled ({len(log_processors)} processor(s))"
        )

    metrics.set_meter_provider(
        MeterProvider(resource=resource, metric_readers=metric_readers)
    )


def setup_instrumentors(app: FastAPI, db_engine: Engine):
    """Instrument app — must be called at module level, before lifespan."""
    Instrumentor(app=app, db_engine=db_engine).instrument()
