# omen-lcd

Linux driver for the round LCD screen on the **HP OMEN AIO liquid cooler** (the one in the OMEN 45L). The screen shows up as USB `03f0:7397` with the name `LCD-PUMP`.

HP only supports this screen through OMEN Gaming Hub on Windows. This project reverse-engineered its USB protocol so you can use the screen on Linux:

- CPU and GPU temperature display, running as a background service
- show any image
- brightness control
- rotation, for coolers mounted sideways

> Not affiliated with or endorsed by HP. Use at your own risk. Everything here only replays messages that OMEN Gaming Hub itself sends. Firmware updates are never touched.

## Status

| Feature | State |
|---|---|
| Identify (model, firmware version) | works |
| Live images (480×480 JPEG) | works |
| Brightness 0–100 / screen off | works |
| CPU temp (Intel `coretemp`), GPU temp (NVIDIA via NVML) | works |
| Power-on effect upload (stored on the pump) | protocol seen, not implemented |
| AMD CPU / AMD GPU temperatures | not yet. PRs welcome |

Tested on firmware `V3.05.024` (OMEN 45L, 2025).

## Install

Requirements: Python 3.10+ and Pillow. NVIDIA GPU temps need the NVIDIA driver (`libnvidia-ml.so.1`). The default face uses Noto Sans fonts at `/usr/share/fonts/noto/`.

```sh
git clone https://github.com/elladann/omen-lcd.git
cd omen-lcd

# let the logged-in user access the screen
sudo install -m 644 udev/70-omen-lcd.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=hidraw

ln -s "$PWD/omen_lcd.py" ~/.local/bin/omen-lcd
omen-lcd info
```

Run the temperature display as a user service:

```sh
cp systemd/omen-lcd.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now omen-lcd
```

## Usage

```sh
omen-lcd info                     # model and firmware
omen-lcd brightness 30            # 0-100, 0 turns the screen dark
omen-lcd image picture.png        # show an image (stays until the next frame)
omen-lcd run                      # temperature display (what the service runs)
omen-lcd run --ring-start '#ff1744' --ring-end '#ffea00'   # ring colours
omen-lcd run --rotate 0           # clockwise degrees; the 45L mounting needs 90 (default)
```

The screen keeps showing the last frame it received. When the service stops, it sends a black frame so stale temperatures don't stay on screen. Before the service starts, for example at boot, the pump plays the power-on effect stored on it.

## How it was reverse-engineered

Protocol details are in [PROTOCOL.md](PROTOCOL.md). The method can be reused for other USB devices that only have Windows software:

1. Run Windows 11 in a VM ([dockur/windows](https://github.com/dockur/windows), see `compose.yaml`) and pass **only** the target USB device through.
2. QEMU's `usb-host` device has a `pcap=` option that records all traffic to a file, with no root needed. Note: it keeps only the first 256 bytes of each transfer.
3. Change one setting at a time in the vendor app, note the time, and diff the captures.

```sh
cp .env.example .env    # set a VM password and where the VM disk goes
docker compose up -d    # then open http://127.0.0.1:8006
```

Captures contain your device's serial number. `captures/` is gitignored, so don't publish raw captures.

## Contributing

Captures from other firmware versions, other OMEN coolers, and AMD sensor support are all welcome. The goal is to upstream this into [liquidctl](https://github.com/liquidctl/liquidctl).

## License

GPL-3.0-or-later
