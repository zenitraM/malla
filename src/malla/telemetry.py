import logging

from flask import Flask
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.instrumentation.system_metrics import SystemMetricsInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

logger = logging.getLogger(__name__)


def setup_telemetry(app: Flask, endpoint: str) -> None:
    """
    Configure OpenTelemetry tracing for the Flask application.

    This sets up comprehensive instrumentation including:
    - Flask HTTP requests
    - SQLite3 database operations
    - Python logging (with trace context injection)
    - HTTP client requests (via requests library)
    - System metrics (CPU, memory, etc.)

    Args:
        app: The Flask application instance.
        endpoint: The OTLP endpoint URL (e.g., "http://localhost:4317").
    """
    if not endpoint:
        logger.info("OTLP endpoint not configured, skipping telemetry setup")
        return

    logger.info(f"Setting up OpenTelemetry with OTLP endpoint: {endpoint}")

    # Create resource with service name
    resource = Resource(attributes={SERVICE_NAME: "malla-web"})

    # Setup trace provider
    provider = TracerProvider(resource=resource)
    processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)

    # Instrument Flask application
    FlaskInstrumentor().instrument_app(app)
    logger.info("Flask instrumentation enabled")

    # Instrument SQLite3 for database tracing
    SQLite3Instrumentor().instrument()
    logger.info("SQLite3 instrumentation enabled")

    # Instrument logging to inject trace context into logs
    LoggingInstrumentor().instrument(set_logging_format=True)
    logger.info("Logging instrumentation enabled (trace context injection)")

    # Instrument requests library for HTTP client tracing
    RequestsInstrumentor().instrument()
    logger.info("Requests instrumentation enabled")

    # Instrument system metrics collection
    SystemMetricsInstrumentor().instrument()
    logger.info("System metrics instrumentation enabled")

    logger.info("OpenTelemetry instrumentation setup complete")
