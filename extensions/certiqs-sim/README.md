# certiqs Sim

Bundled certiqsSim control plane and Run Control for certiqs IDE.

Results are **synthetic**. They are **not a measurement** and **not a security or conformity statement**.

## Open the extension

Click the **beaker** in the activity bar (below certiqs Assurance).

- Left sidebar: **Run Control** — start and stop the local API and one simulation run
- Editor: **Overview and documentation** — this welcome page

Command Palette: `certiqs: Open Sim` or `certiqs: Open Sim Overview`.

## Start a simulation

1. Wait until Run Control shows **API ready** (auto-start is on by default).
2. Choose a bundled YAML configuration (`bbm92-minimal`, `bbm92-generic`, or `bbm92-minimal-integrated`).
3. Set shots per epoch (minimum 1000).
4. Press **Start simulation**. Press **Stop** to finish the current epoch and shut the run down.

A trusted workspace is required.

## How it is wired

The extension host owns `python -m certiqs_sim.services.api` and all HTTP to `127.0.0.1` (default port **8011**). The webview only sends typed messages. It never opens that connection.

If `certiqs.sim.pythonPath` is left at `python3`, the host uses `python/.venv` when that virtualenv exists.

Control-plane extras:

```bash
python3 -m pip install -r extensions/certiqs-sim/python/requirements-ide.txt
```

NetSquid is optional and comes from a private index. The API can start without it. A run cannot.

## Settings

Open the right sidebar tab **certiqs Settings** (next to HQ), or run `certiqs: Open certiqs Settings`.

Field definitions for this extension live in `extensions/certiqs-sim/settings.json`. HQ only renders the shell; it discovers contributors via `contributes.certiqsSettings`.

NetSquid credentials are entered on the **Engine** page:

- Username and optional index URL → user settings (`certiqs.sim.netsquidPypiUser`, `certiqs.sim.netsquidPypiUrl`)
- Password → certiqs IDE secret storage for this profile (not the workspace, not `settings.json`)

Then use **Install NetSquid**. The install log is in the **certiqs Sim** output channel; the index URL is redacted.

| Setting | Default | Purpose |
|---|---|---|
| `certiqs.sim.pythonPath` | `python3` | Interpreter for the control plane |
| `certiqs.sim.port` | `8011` | Localhost port |
| `certiqs.sim.autoStartApi` | `true` | Start the API when Run Control opens |

Logs go to the **certiqs Sim** output channel (`certiqs: Show Sim Log`).
