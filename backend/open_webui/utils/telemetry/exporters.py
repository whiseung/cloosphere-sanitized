from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter


class LazyBatchSpanProcessor(BatchSpanProcessor):
    """BatchSpanProcessor that only starts processing when the first span arrives."""

    def __init__(self, span_exporter: SpanExporter, **kwargs):
        self._span_exporter = span_exporter
        self._kwargs = kwargs
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            super().__init__(self._span_exporter, **self._kwargs)
            self._initialized = True

    def on_start(self, span, parent_context=None):
        self._ensure_initialized()
        super().on_start(span, parent_context)

    def on_end(self, span: ReadableSpan) -> None:
        self._ensure_initialized()
        super().on_end(span)

    def shutdown(self) -> None:
        if self._initialized:
            super().shutdown()
        else:
            self._span_exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        if self._initialized:
            return super().force_flush(timeout_millis)
        return True
