"""External worker microservice clients (GHCR containers → main app via gRPC)."""

from certiqs_sim.external.client import probe_worker_grpc

__all__ = ["probe_worker_grpc"]  # ServiceRuntime + legacy WorkerService probe
