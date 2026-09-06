"""certiqsSim — QKD Evaluation & Assurance Framework.

NetSquid live twin simulation, attack/defence evaluation, and monitoring
(BBM92 default reference protocol). The package is layered so the domain
physics (``core``) has no dependency on any framework, service, or transport.
Higher layers build on it:

``core``            NetSquid quantum-channel twin, protocol plugins, detectors,
                    attacks, and countermeasures (framework-free).
``postprocessing``  sifting audit, QBER sampling, error correction (Cascade),
                    privacy amplification (Toeplitz), and finite-key analysis.
``config``          typed pydantic models mirroring the 8 YAML manifest docs.
``telemetry``       structlog JSON logging + Prometheus metrics.
``persistence``     SQLAlchemy models & repositories for datapoints/provenance.
``bus``             pluggable event backbone (in-memory / NATS / Redis).
``runtime``         the continuous twin worker + tunable-parameter surface.
``services``        API gateway, engine, post-processing, and security-eval apps.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
