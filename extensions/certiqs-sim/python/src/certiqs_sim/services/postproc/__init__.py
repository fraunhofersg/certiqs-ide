"""certiqs-postproc: consumes sifted blocks and runs the post-processing pipeline.

Subscribes to ``*.runs.*.sifted`` on the bus, performs QBER sampling, Cascade
error correction, finite-key analysis, and Toeplitz privacy amplification, then
publishes a ``*.runs.<id>.postproc`` result.  This is the deployable microservice
form of :mod:`certiqs_sim.postprocessing`; the API/engine also run the same
pipeline inline for the live estimate.
"""

from __future__ import annotations

from certiqs_sim.services.postproc.app import create_app

__all__ = ["create_app"]
