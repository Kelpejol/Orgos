"""OpenTelemetry setup for OrgOS.

The app exports traces, metrics, and logs over OTLP/HTTP when either
OTEL_ENABLED=true or an OTLP endpoint is configured. Standard OTEL_* environment
variables are supported so infrastructure can wire this to Grafana Alloy,
OpenTelemetry Collector, or Grafana Cloud without code changes.
"""

from __future__ import annotations

import logging
import os
import socket
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Mapping, Optional

logger = logging.getLogger(__name__)

_INITIALIZED = False
_TRACER_PROVIDER = None
_METER_PROVIDER = None
_LOGGER_PROVIDER = None
_COUNTERS: Dict[str, Any] = {}


def setup_observability(app: Any, settings: Any) -> None:
    """Configure OpenTelemetry exporters and auto-instrumentation."""
    global _INITIALIZED, _TRACER_PROVIDER, _METER_PROVIDER, _LOGGER_PROVIDER

    if _INITIALIZED:
        return

    if not _is_enabled(settings):
        logger.info("OpenTelemetry disabled; set OTEL_EXPORTER_OTLP_ENDPOINT to enable")
        return

    try:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.logging import LoggingInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("OpenTelemetry requested but dependencies are missing: %s", exc)
        return

    headers = _parse_headers(_setting(settings, "otel_exporter_otlp_headers", ""))
    resource = Resource.create(
        {
            "service.name": _service_name(settings),
            "service.version": _setting(settings, "otel_service_version", "1.0.0"),
            "deployment.environment": settings.environment,
            "host.name": socket.gethostname(),
        }
    )

    if _setting_bool(settings, "otel_traces_enabled", True):
        trace_endpoint = _signal_endpoint(settings, "traces")
        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=trace_endpoint, headers=headers))
        )
        trace.set_tracer_provider(tracer_provider)
        _TRACER_PROVIDER = tracer_provider

    if _setting_bool(settings, "otel_metrics_enabled", True):
        metrics_endpoint = _signal_endpoint(settings, "metrics")
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=metrics_endpoint, headers=headers),
            export_interval_millis=_setting_int(settings, "otel_metrics_interval_ms", 60000),
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
        _METER_PROVIDER = meter_provider

    if _setting_bool(settings, "otel_logs_enabled", True):
        logs_endpoint = _signal_endpoint(settings, "logs")
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=logs_endpoint, headers=headers))
        )
        set_logger_provider(logger_provider)
        logging.getLogger().addHandler(
            LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
        )
        LoggingInstrumentor().instrument(set_logging_format=False)
        _LOGGER_PROVIDER = logger_provider

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls=_setting(settings, "otel_excluded_urls", ""),
    )
    HTTPXClientInstrumentor().instrument()

    _INITIALIZED = True
    logger.info(
        "OpenTelemetry enabled for service=%s endpoint=%s",
        _service_name(settings),
        _setting(settings, "otel_exporter_otlp_endpoint", "")
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
    )


def shutdown_observability() -> None:
    """Flush telemetry during graceful application shutdown."""
    for provider in (_METER_PROVIDER, _TRACER_PROVIDER, _LOGGER_PROVIDER):
        if provider is None:
            continue
        shutdown = getattr(provider, "shutdown", None)
        if shutdown is None:
            continue
        try:
            shutdown()
        except Exception as exc:
            logger.warning("OpenTelemetry provider shutdown failed: %s", exc)


@contextmanager
def start_span(name: str, **attributes: Any) -> Iterator[Optional[Any]]:
    """Start a span if OpenTelemetry is installed; otherwise act as a no-op."""
    try:
        from opentelemetry import trace
    except ImportError:
        yield None
        return

    with trace.get_tracer("orgos").start_as_current_span(name) as span:
        for key, value in attributes.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def record_counter(
    name: str,
    value: int = 1,
    attributes: Optional[Mapping[str, Any]] = None,
    description: str = "",
) -> None:
    """Increment an OpenTelemetry counter if metrics are available."""
    try:
        from opentelemetry import metrics
    except ImportError:
        return

    counter = _COUNTERS.get(name)
    if counter is None:
        counter = metrics.get_meter("orgos").create_counter(
            name,
            description=description,
        )
        _COUNTERS[name] = counter
    counter.add(value, dict(attributes or {}))


def _is_enabled(settings: Any) -> bool:
    return (
        _setting_bool(settings, "otel_enabled", False)
        or bool(_setting(settings, "otel_exporter_otlp_endpoint", ""))
        or bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
        or bool(os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", ""))
        or bool(os.getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", ""))
        or bool(os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", ""))
    )


def _signal_endpoint(settings: Any, signal: str) -> Optional[str]:
    env_key = f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT"
    endpoint = os.getenv(env_key, "").strip()
    if endpoint:
        return endpoint

    endpoint = _setting(settings, f"otel_exporter_otlp_{signal}_endpoint", "")
    if endpoint:
        return endpoint

    endpoint = (
        _setting(settings, "otel_exporter_otlp_endpoint", "")
        or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    ).strip()
    if not endpoint:
        return None
    return _append_signal_path(endpoint, signal)


def _append_signal_path(endpoint: str, signal: str) -> str:
    endpoint = endpoint.rstrip("/")
    if f"/v1/{signal}" in endpoint:
        return endpoint
    return f"{endpoint}/v1/{signal}"


def _parse_headers(value: str) -> Optional[Dict[str, str]]:
    value = (value or os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")).strip()
    if not value:
        return None

    headers: Dict[str, str] = {}
    for item in value.split(","):
        key, separator, header_value = item.partition("=")
        if separator and key.strip():
            headers[key.strip()] = header_value.strip()
    return headers or None


def _service_name(settings: Any) -> str:
    return (
        os.getenv("OTEL_SERVICE_NAME", "").strip()
        or _setting(settings, "otel_service_name", "orgos-api")
    )


def _setting(settings: Any, name: str, default: str) -> str:
    value = getattr(settings, name, default)
    return str(value).strip() if value is not None else default


def _setting_bool(settings: Any, name: str, default: bool) -> bool:
    value = getattr(settings, name, default)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _setting_int(settings: Any, name: str, default: int) -> int:
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default
