# BBM92 Minimal Integrated Configuration

Variant of `bbm92-minimal` where the entangled-photon **source is co-located
inside Alice's node** as a *separate box* (`box_source_01`), alongside her
measurement box (`box_alice_01`). There is no standalone source node.

## How it differs from `bbm92-minimal`

- **Two nodes** instead of three: `node_alice` (source box + measurement box)
  and `node_bob`.
- `node_alice` owns two devices under `devices/`; the source's domains/modules/components
  (`pump_laser`, `spdc_crystal`) live in `devices/device_source_01/`.
- **`qch_source_alice`** is now an **intra-node** link (source box → Alice
  measurement box, `pkg_alice` → `pkg_alice`).
- **`qch_source_bob`** stays a **cross-node** fiber link, now originating from
  Alice's node (`pkg_alice` → `pkg_bob`). The Bob arm is exposed as the
  `source_out_bob` boundary port on `node_alice`.
- Everything else (detectors, timing, post-processing, coincidence on Alice)
  is identical to `bbm92-minimal`.

## Intra-node vs cross-node links

Links are authored by scope, so each node is self-contained:

- **Intra-node links** (both endpoints inside one node) live in that node's
  `node.yaml` under `channels:` (physics) and `connections:` (port wiring). In
  this config, `nodes/alice/node.yaml` owns `qch_source_alice`
  (source device → Alice measurement device) and `cch_alice_relay` (Alice
  measurement device → node KMS relay port).
- **Cross-node links** (leaving a node) stay in `network/channels.yaml`:
  `qch_source_bob`, `cch_alice_bob`, and the sync channels.

The loader/adapter aggregate both sources generically from configuration — no
node or channel identities are hard-coded — so moving a link between the node
file and the network file changes only where it is declared, not how it renders.

## Classical channel as a trusted-node relay

The authenticated classical channel to Bob is modelled as a **trusted-node
relay** rather than a direct box↔box link:

1. `cch_alice_relay` (intra-node, `pkg_alice` → `pkg_alice`): the Alice
   measurement device port `kx1_alice` hands key material to the node-level
   relay port `kx1_alice_relay` (owned by the Alice KMS agent `alice_kma`).
2. `cch_alice_bob` (cross-node, `pkg_alice` → `pkg_bob`): the node relay port
   `kx1_alice_relay` connects out to Bob's `kx1_bob`.

Because `kx1_alice_relay` is owned by a node-level entity (the KMS), it renders
on the **Alice node frame**, so the cross-node line attaches to the node — not
directly to the measurement box. To change this at runtime, enable **Edit
topology**, right-click the classical line, choose *Reconnect source/target…*,
and pick another compatible connector (validated by edge kind / direction).

## Where to edit common parameters

| Goal | File |
|------|------|
| Fiber length / loss (source→Bob) | `network/channels.yaml` → `channels.qch_source_bob` |
| Fiber length / loss (source→Alice) | `nodes/alice/node.yaml` → `channels.qch_source_alice` |
| Coincidence window | `network/control.yaml` + `shared/protocol.yaml` |
| Source (pump / SPDC) | `nodes/alice/components.yaml` → `pump_laser`, `spdc_crystal` |
| Detector efficiency | `nodes/{alice,bob}/components.yaml` → `*_detector_*` |
| Sifting / QBER abort | `nodes/alice/kms/post_processing.yaml` |
| Bob post-processing | `nodes/bob/kms/post_processing.yaml` |

## Package layout

```
network/       system topology, channels, timing
nodes/alice/   co-located source box + measurement + authoritative coincidence
nodes/bob/     measurement + reconciliation / PA / key export
shared/        protocol parameters
```
