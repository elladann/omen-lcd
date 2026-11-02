# HP OMEN AIO LCD (`03f0:7397`, "LCD-PUMP") — USB protocol notes

Captured 2026-11-02 from OMEN Gaming Hub 1101.2609.11.0 in a Windows 11 VM (QEMU usb-host pcap).
The device reports `2N9,01,HS,SQ,OMEN-LCD-CAP,V3.05.024,0.1`, firmware build `Jun 18 2025,13:50:35`.

Verified from Linux (hidraw): identify, live frames, brightness. The rest is from captures only.
Caveat: QEMU's pcap keeps only the first 256 bytes of each 1024-byte OUT transfer. Small commands are complete; bulk payloads are truncated.

## Transport

- USB HID, two interfaces. Host → device: interrupt OUT EP `0x02` (1024-byte max packet). Device → host: interrupt IN EP `0x81` (512 bytes), plus EP `0x83` (8 bytes).
- Every message starts with a report ID: `0x01` = 64-byte command, `0x02` = 1024-byte data/command.
- Byte 1 is the opcode.

## Commands (report `0x01`, 64 bytes, zero-padded)

| Bytes | Meaning | Reply on EP 0x81 |
|---|---|---|
| `01 46 00…` | Identify | Two replies: `01 46 00 00 00 32 "2N9,01,HS,SQ,OMEN-LCD-CAP,V3.05.024,0.1"`, then `01 46 00 00 01 1b "Jun 18 2025,13:50:35"` |
| `01 41 00 00 00 01 00…` | Status poll (sent often) | `01 41 00 00 00 07 00…` |

## Data messages (report `0x02`, 1024 bytes)

Common header, 11 bytes:

```
02 <op> <total_len: u32 BE> <chunk_index: u24 BE> <chunk_len: u16 BE> <chunk data…>
```

The payload is split into chunks of up to 1013 bytes (`0x03f5`). 11 + 1013 = 1024.

| Op | Meaning |
|---|---|
| `0x6e` | **Live frame.** Payload = one baseline JPEG, 480×480. OGH streams ~18 fps continuously. Rotation set in OGH is applied host-side (no rotation command seen), so the device just shows what it is sent. |
| `0x6c` | **Display settings.** Seen: `02 6c 00 00 00 01 00 00 01 00 08 04 <brightness> 00 00 00 00 00 19 00…`. Brightness `0x00`–`0x64` (0–100). The OGH "ON" toggle sends brightness 0 / 100. The device echoes it on EP 0x81 as a 512-byte report. |
| `0x76` | **Upload power-on effect** (stored on the device). Payload = a RIFF AVI (MJPEG frames). Example: 640214 bytes in 632 chunks, ~21 s at ~30 chunks/s. |
| `0x7b` | Sent right after the `0x76` upload: `02 7b 00 00 00 01 00 00 01 00 08 01`. Probably commit/activate the stored effect. Unconfirmed. |

## Open questions

- What the screen shows when no host is streaming (stored effect? last frame?). Is a frame keep-alive needed?
- Meaning of `0x19` in `0x6c` (25: frame rate? timeout?).
- AVI constraints for `0x76` (resolution, codec, max size). Needs a full (untruncated) capture.
- EP `0x83` (8-byte IN): not yet seen carrying data.
