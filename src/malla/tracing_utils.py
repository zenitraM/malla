"""
OpenTelemetry tracing utilities for adding custom spans to functions.

This module provides decorators and utilities for manual instrumentation
of specific functions and code blocks.
"""

from collections.abc import Callable
from functools import wraps
from typing import Any

from opentelemetry import trace

# Get a tracer for this application
tracer = trace.get_tracer(__name__)


def traced(span_name: str | None = None):
    """
    Decorator to create a span for a function.

    This decorator automatically creates a span that tracks the execution
    of the decorated function, including timing and any exceptions.

    Args:
        span_name: Optional custom name for the span. If not provided,
                   uses the function's qualified name.

    Example:
        @traced("process_packet")
        def process_packet(packet_data):
            # Function logic here
            pass

        # Or with automatic naming:
        @traced()
        def calculate_metrics():
            # Function logic here
            pass
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Use custom span name or fall back to function name
            name = span_name or f"{func.__module__}.{func.__qualname__}"

            with tracer.start_as_current_span(name) as span:
                # Add function metadata as span attributes
                span.set_attribute("function.name", func.__name__)
                span.set_attribute("function.module", func.__module__)

                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    # Record exception in span
                    span.record_exception(e)
                    span.set_status(trace.Status(trace.StatusCode.ERROR, str(e)))
                    raise

        return wrapper

    return decorator


def add_span_attributes(**attributes: Any) -> None:
    """
    Add custom attributes to the current active span.

    This is useful for adding contextual information to spans created
    by auto-instrumentation or parent spans.

    Args:
        **attributes: Key-value pairs to add as span attributes.

    Example:
        def process_node(node_id):
            add_span_attributes(node_id=node_id, node_type="sensor")
            # ... rest of function
    """
    current_span = trace.get_current_span()
    if current_span and current_span.is_recording():
        for key, value in attributes.items():
            current_span.set_attribute(key, value)
