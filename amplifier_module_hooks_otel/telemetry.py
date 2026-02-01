"""Public telemetry API for applications.

This module provides a simple API for applications (like amplifier-app-cli) to emit
bundle telemetry events. Applications call these functions when performing bundle
operations, and this module handles the OpenTelemetry instrumentation.

Usage in applications:
    from amplifier_module_hooks_otel import telemetry

    # When user runs: amplifier bundle add git+https://github.com/org/my-bundle
    telemetry.bundle_added(
        name="my-bundle",
        source="git+https://github.com/org/my-bundle",
    )

    # When user runs: amplifier bundle use my-bundle
    telemetry.bundle_activated(
        name="my-bundle",
        version="1.0.0",
        source="git+https://github.com/org/my-bundle",
    )

Privacy:
    Local paths are automatically sanitized to "local" to protect privacy.
    Git URLs (git+https://, https://, git@, ssh://) are preserved as they are public.

Graceful Degradation:
    If OpenTelemetry is not initialized (hook not mounted), these functions
    are safe to call - they simply no-op.

Thread Safety:
    _register() and _unregister() should only be called once during module
    mount/unmount. Concurrent calls are not supported. Once initialized,
    the module-level variables are only read, not written.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .attributes import sanitize_bundle_source

if TYPE_CHECKING:
    from .metrics import MetricsRecorder
    from .spans import SpanManager

logger = logging.getLogger(__name__)

# Module-level registry populated by the hook when initialized
_metrics_recorder: MetricsRecorder | None = None
_span_manager: SpanManager | None = None
_initialized: bool = False


def _register(metrics_recorder: MetricsRecorder, span_manager: SpanManager) -> None:
    """Register OTel components (called by hook on initialization).

    This is an internal function called by the hook module when it initializes.
    Applications should not call this directly.

    Thread Safety: This function should only be called once during module mount.
    Concurrent calls are not supported.

    Args:
        metrics_recorder: The MetricsRecorder instance from the hook.
        span_manager: The SpanManager instance from the hook.
    """
    global _metrics_recorder, _span_manager, _initialized
    _metrics_recorder = metrics_recorder
    _span_manager = span_manager
    _initialized = True
    logger.debug("Telemetry API registered with OTel components")


def _unregister() -> None:
    """Unregister OTel components (called by hook on shutdown).

    This is an internal function called by the hook module when it shuts down.
    Applications should not call this directly.
    """
    global _metrics_recorder, _span_manager, _initialized
    _metrics_recorder = None
    _span_manager = None
    _initialized = False
    logger.debug("Telemetry API unregistered")


def is_initialized() -> bool:
    """Check if the telemetry API is initialized and ready to use.

    Returns:
        True if OTel components are registered, False otherwise.
    """
    return _initialized


def _emit_bundle_span(
    operation: str,
    name: str,
    version: str | None,
    source: str | None,
    extra_attrs: dict[str, Any] | None = None,
) -> None:
    """Emit a span for a bundle operation.

    Args:
        operation: Operation name (add, activate, load).
        name: Bundle name.
        version: Bundle version (optional).
        source: Sanitized bundle source (optional).
        extra_attrs: Additional span attributes.
    """
    if _span_manager is None:
        return

    attributes: dict[str, Any] = {
        "amplifier.bundle.name": name,
        "amplifier.bundle.operation": operation,
    }
    if version:
        attributes["amplifier.bundle.version"] = version
    if source and source != "unknown":
        attributes["amplifier.bundle.source"] = source
    if extra_attrs:
        attributes.update(extra_attrs)

    span = _span_manager.create_standalone_span(f"bundle.{operation}", attributes)
    span.end()


def bundle_added(
    name: str,
    source: str | None = None,
    version: str | None = None,
) -> None:
    """Record a bundle being added/installed.

    Call this when a bundle is added to the system (e.g., `amplifier bundle add`).

    Args:
        name: Name of the bundle.
        source: Source URI or path (automatically sanitized for privacy).
        version: Version of the bundle (optional).

    Example:
        >>> from amplifier_module_hooks_otel import telemetry
        >>> telemetry.bundle_added(
        ...     name="recipes",
        ...     source="git+https://github.com/microsoft/amplifier-bundle-recipes",
        ...     version="1.0.0",
        ... )
    """
    if not _initialized or _metrics_recorder is None:
        logger.debug(f"Telemetry not initialized, skipping bundle_added for '{name}'")
        return

    # Sanitize source for privacy (handles None -> "unknown")
    sanitized_source = sanitize_bundle_source(source)

    # Record metric
    _metrics_recorder.record_bundle_used(
        bundle_name=name,
        bundle_version=version,
        bundle_source=sanitized_source,
    )

    # Emit span
    _emit_bundle_span("add", name, version, sanitized_source)

    logger.debug(f"Recorded bundle_added: {name}")


def bundle_activated(
    name: str,
    source: str | None = None,
    version: str | None = None,
) -> None:
    """Record a bundle being activated/used.

    Call this when a bundle is set as active (e.g., `amplifier bundle use`).

    Args:
        name: Name of the bundle.
        source: Source URI or path (automatically sanitized for privacy).
        version: Version of the bundle (optional).

    Example:
        >>> from amplifier_module_hooks_otel import telemetry
        >>> telemetry.bundle_activated(
        ...     name="foundation",
        ...     source="git+https://github.com/microsoft/amplifier-foundation",
        ... )
    """
    if not _initialized or _metrics_recorder is None:
        logger.debug(f"Telemetry not initialized, skipping bundle_activated for '{name}'")
        return

    # Sanitize source for privacy (handles None -> "unknown")
    sanitized_source = sanitize_bundle_source(source)

    # Record metric
    _metrics_recorder.record_bundle_used(
        bundle_name=name,
        bundle_version=version,
        bundle_source=sanitized_source,
    )

    # Emit span
    _emit_bundle_span("activate", name, version, sanitized_source)

    logger.debug(f"Recorded bundle_activated: {name}")


def bundle_loaded(
    name: str,
    source: str | None = None,
    version: str | None = None,
    cached: bool = False,
) -> None:
    """Record a bundle being loaded.

    Call this when a bundle is loaded from cache or disk.

    Args:
        name: Name of the bundle.
        source: Source URI or path (automatically sanitized for privacy).
        version: Version of the bundle (optional).
        cached: Whether the bundle was loaded from cache.

    Example:
        >>> from amplifier_module_hooks_otel import telemetry
        >>> telemetry.bundle_loaded(
        ...     name="foundation",
        ...     source="git+https://github.com/microsoft/amplifier-foundation",
        ...     cached=True,
        ... )
    """
    if not _initialized or _metrics_recorder is None:
        logger.debug(f"Telemetry not initialized, skipping bundle_loaded for '{name}'")
        return

    # Sanitize source for privacy (handles None -> "unknown")
    sanitized_source = sanitize_bundle_source(source)

    # Record metric
    _metrics_recorder.record_bundle_used(
        bundle_name=name,
        bundle_version=version,
        bundle_source=sanitized_source,
    )

    # Emit span with cached attribute
    _emit_bundle_span(
        "load",
        name,
        version,
        sanitized_source,
        extra_attrs={"amplifier.bundle.cached": cached},
    )

    logger.debug(f"Recorded bundle_loaded: {name} (cached={cached})")
