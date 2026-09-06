# BBM92 Minimal Configuration

Condensed reference model derived from `bbm92-generic`. Optimized for human editing.

## What was simplified

- **Detector path**: SPAD → TDC directly (no per-channel bias/frontend/discriminator chain).
- **Source**: pump laser + SPDC only; boundary ports on the crystal.
- **Domains**: fewer subdomains; software keeps required pipeline stages as named placeholders.
- **Network**: channel bindings only (no duplicate flat `connections` block).
- **Dropped**: experiments bundle, legacy archive, heavy catalog/taxonomy.

## Where to edit common parameters

| Goal | File |
|------|------|
| Fiber length / loss | `network/channels.yaml` → `channels.qch_source_*` |
| Coincidence window | `network/control.yaml` + `shared/protocol.yaml` |
| Detector efficiency | `nodes/{alice,bob}/components.yaml` → `*_detector_*` |
| Sifting / QBER abort | `nodes/alice/kms/post_processing.yaml` |
| Bob post-processing | `nodes/bob/kms/post_processing.yaml` |

## Signal flow (measurement node)

```
quantum_in → PAM → 4× SPAD → TDC → timestamps_out (boundary)
```

Coincidence correlation runs on **Alice** only; the source distributes photon pairs.

## Package layout

```
network/     system topology, channels, timing
nodes/source/   entangled pair source (no key processing)
nodes/alice/    measurement + authoritative coincidence + sifting
nodes/bob/      measurement + reconciliation / PA / key export
shared/         protocol parameters
```
