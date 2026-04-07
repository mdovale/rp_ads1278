# rp_ads1278 client

Python desktop client for the `rp_ads1278` Red Pitaya server. It validates the
`RP_CAP:ads1278_v1` handshake, decodes the fixed 60-byte server messages, plots
eight live channels, sends the three control commands, and optionally logs
`SAMPLE` messages to CSV.

## Install

From the repo root, using the shared `.venv`:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ./client
```

Optional test dependencies:

```bash
.venv/bin/python -m pip install -e "./client[dev]"
```

## Run

From the repo root:

```bash
.venv/bin/python client/main.py
```

Or after installation:

```bash
.venv/bin/ads1278-client
```

The GUI defaults to `127.0.0.1:5000`. Enter the Red Pitaya host, connect, and
use the command bar to enable streaming, trigger `SYNC`, change `EXTCLK_DIV`,
and start or stop CSV logging.

The current server requires `EXTCLK_DIV >= 3`. The GUI enforces that minimum and
rejects smaller values before sending them.

## Fake server

For host-side bring-up without hardware:

```bash
PYTHONPATH=client .venv/bin/python client/tools/fake_server.py --demo-sequence
```

This fake server sends the real capability line, an initial `SAMPLE`, optional
demo `ACK`/`ERROR` messages, and periodic `SAMPLE` updates once acquisition is
enabled.

## Tests

From the repo root:

```bash
PYTHONPATH=client .venv/bin/python -m pytest client/tests -v
```
