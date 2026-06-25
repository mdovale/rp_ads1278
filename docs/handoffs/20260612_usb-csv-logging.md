# rp_ads1278 — USB CSV logging handoff

Date: 2026-06-12

## Summary

Implemented client-controlled CSV logging to a USB flash stick mounted on the Red Pitaya. The primary use case is a timed unattended capture: arm logging from the GUI, optionally disconnect the GUI and SSH, and let `ads1278-server` continue writing until the server-side deadline expires.

The fixed USB mount convention is:

```bash
mkdir -p /mnt/usb
mount /dev/sda1 /mnt/usb
mkdir -p /mnt/usb/ads1278/logs
```

The server default log directory is `/mnt/usb/ads1278/logs`; override it with `--log-dir PATH`.

## Operator workflow

1. Plug in the USB stick.
2. SSH into the Red Pitaya and mount it:

   ```bash
   lsblk
   mkdir -p /mnt/usb
   mount /dev/sda1 /mnt/usb
   mkdir -p /mnt/usb/ads1278/logs
   touch /mnt/usb/_test && rm /mnt/usb/_test
   ```

3. Start the server persistently, preferably through systemd. The recommended command is:

   ```bash
   /root/ads1278-server --dma-bulk --poll-ms 0 --log-dir /mnt/usb/ads1278/logs
   ```

4. In the GUI:
   - Connect to the board.
   - Set **Save CSV to** to **USB on Red Pitaya**.
   - Set the CSV filename.
   - Set a positive duration for unattended capture.
   - Click **Start CSV** and wait for the status to report logging active.
   - Enable acquisition.
   - Disconnect the GUI if desired.

5. After the duration elapses, retrieve files from:

   ```bash
   /mnt/usb/ads1278/logs
   ```

6. Before unplugging:

   ```bash
   sync
   umount /mnt/usb
   ```

## Behavior matrix

| Mode | Timer owner | GUI disconnect | SSH disconnect when server runs via systemd |
|------|-------------|----------------|---------------------------------------------|
| Host CSV, manual | None | Stops | N/A |
| Host CSV, timed | Client | Stops | N/A |
| USB CSV, manual | None | Stops | Continues only while client remains connected or until manual stop |
| USB CSV, timed | Server | Continues until deadline | Continues until deadline |

Closing SSH only preserves logging if the server process is not a foreground child of that SSH session. Use systemd for long captures.

## Implementation notes

- `server/csv_logger.c` owns USB CSV directory checks, filename validation, headers, rows, and close behavior.
- Protocol opcodes:
  - `6 START_LOCAL_LOG`
  - `7 STOP_LOCAL_LOG`
  - `8 SET_LOCAL_LOG_DURATION`
  - `9 SET_LOCAL_LOG_FILENAME`
- Filename chunks are 3 ASCII bytes per command, with chunk index in bits `31:24`.
- Channel mask `0` means all eight channels.
- Timed unattended logging requires a positive duration before `START_LOCAL_LOG`.
- If `/mnt/usb` is not mounted, `START_LOCAL_LOG` returns `ERROR`.

## Hardware QA checklist

- [ ] Mounted USB path passes `touch /mnt/usb/_test && rm /mnt/usb/_test`.
- [ ] `systemctl start ads1278-server` starts `/root/ads1278-server --dma-bulk --poll-ms 0 --log-dir /mnt/usb/ads1278/logs`.
- [ ] Timed USB capture creates a file with the requested basename.
- [ ] File keeps growing after GUI disconnect.
- [ ] File keeps growing after SSH disconnect when server is run by systemd.
- [ ] File stops growing shortly after the requested duration.
- [ ] Manual USB capture stops on GUI disconnect.
- [ ] `STOP_LOCAL_LOG` ACK row count matches CSV data rows for manual capture.
- [ ] Negative test: unmounted `/mnt/usb` returns `ERROR START_LOCAL_LOG` and the server stays alive.
- [ ] `sync && umount /mnt/usb` succeeds before unplugging.

## Known limitations

- USB auto-mount is not implemented; mount manually before capture.
- The protocol duration is whole seconds; the client rounds fractional durations up.
- CSV is verbose and synchronous. Use `--dma-bulk --poll-ms 0` for sustained captures.
- Capture does not survive Red Pitaya reboot or killing `ads1278-server`.
- There is no completion sidecar file; use elapsed time and file size to confirm completion.
