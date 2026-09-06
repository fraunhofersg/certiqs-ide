"""Load NetSquid on the main thread.

NetSquid registers SIGINT handlers at import. FastAPI runs sync routes on a
threadpool, so the first ``import netsquid`` from ``POST /api/v1/runs`` raises
``ValueError: signal only works in main thread of the main interpreter``.
Import the engine here during process startup, while we are still on the
main thread. Later worker-thread imports then reuse the loaded module.
"""

from __future__ import annotations


def preload_netsquid() -> bool:
    try:
        import netsquid  # noqa: F401
        from certiqs_sim.runtime.worker import TwinWorker  # noqa: F401
    except ImportError:
        return False
    return True
