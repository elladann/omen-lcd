#!/usr/bin/env python3
"""Drive the HP OMEN AIO LCD ("LCD-PUMP", USB 03f0:7397) from Linux.

Protocol notes: PROTOCOL.md. Needs only Pillow; NVIDIA GPU temps come from NVML (libnvidia-ml).

    omen-lcd info                 # identify the device
    omen-lcd brightness 0-100     # 0 = screen dark
    omen-lcd image FILE           # show a picture once (it stays until the next frame)
    omen-lcd run                  # CPU/GPU temperature display (the service runs this)
"""
from __future__ import annotations

import argparse
import ctypes
import glob
import io
import math
import os
import select
import signal
import sys
import time

from PIL import Image, ImageDraw, ImageFont

VID, PID = 0x03F0, 0x7397
SIZE = 480            # the panel is 480x480, round
CHUNK = 1013          # payload bytes per 1024-byte report (11-byte header)
OP_FRAME = 0x6E
OP_SETTINGS = 0x6C
FONT_BOLD = "/usr/share/fonts/noto/NotoSans-Bold.ttf"
FONT_REGULAR = "/usr/share/fonts/noto/NotoSans-Regular.ttf"


# ---------------------------------------------------------------- device

def find_hidraw() -> str:
    """The pump has two HID interfaces; the one with the OUT endpoint (ep_02) takes commands."""
    want = f"{VID:08X}:{PID:08X}"
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev = os.path.realpath(os.path.join(node, "device"))
        try:
            uevent = open(os.path.join(dev, "uevent")).read()
        except OSError:
            continue
        if want in uevent and os.path.exists(os.path.join(dev, "..", "ep_02")):
            return "/dev/" + os.path.basename(node)
    raise FileNotFoundError("OMEN LCD (03f0:7397) not found")


class LCD:
    def __init__(self, path: str | None = None):
        self.path = path or find_hidraw()
        self.fd = os.open(self.path, os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def _drain(self, timeout=0.0, gap=0.05) -> list[bytes]:
        out = []
        while select.select([self.fd], [], [], timeout)[0]:
            out.append(os.read(self.fd, 1024))
            timeout = gap
        return out

    def command(self, op: int, *args: int) -> list[bytes]:
        self._drain()
        os.write(self.fd, bytes([0x01, op, *args]).ljust(64, b"\0"))
        return self._drain(1.0, gap=1.5)

    def _send(self, op: int, payload: bytes):
        n = len(payload)
        for i in range(max(1, math.ceil(n / CHUNK))):
            part = payload[i * CHUNK:(i + 1) * CHUNK]
            head = bytes([0x02, op]) + n.to_bytes(4, "big") + i.to_bytes(3, "big") + len(part).to_bytes(2, "big")
            os.write(self.fd, (head + part).ljust(1024, b"\0"))
        self._drain()  # discard status echoes so the input queue never fills

    def info(self) -> list[str]:
        return [r[6:].split(b"\0")[0].decode(errors="replace") for r in self.command(0x46) if r[:2] == b"\x01\x46"]

    def brightness(self, level: int):
        level = max(0, min(100, level))
        # Exactly what OMEN Gaming Hub sends: an 8-byte settings block, chunk index 1.
        block = bytes([0x04, level, 0, 0, 0, 0, 0, 0x19])
        head = bytes([0x02, OP_SETTINGS]) + (1).to_bytes(4, "big") + (1).to_bytes(3, "big") + len(block).to_bytes(2, "big")
        os.write(self.fd, (head + block).ljust(1024, b"\0"))
        self._drain(0.3)

    def frame(self, img: Image.Image, rotate: int = 0):
        img = img.convert("RGB").resize((SIZE, SIZE))
        if rotate:
            img = img.rotate(-rotate)  # rotate is clockwise degrees; PIL rotates counter-clockwise
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=90)
        self._send(OP_FRAME, buf.getvalue())


# ---------------------------------------------------------------- sensors

def cpu_temp() -> float | None:
    for name in glob.glob("/sys/class/hwmon/hwmon*/name"):
        if open(name).read().strip() != "coretemp":
            continue
        d = os.path.dirname(name)
        for label in glob.glob(d + "/temp*_label"):
            if open(label).read().startswith("Package"):
                return int(open(label.replace("_label", "_input")).read()) / 1000
    return None


class NvidiaGPU:
    def __init__(self):
        self.lib = self.handle = None
        try:
            lib = ctypes.CDLL("libnvidia-ml.so.1")
            if lib.nvmlInit_v2() == 0:
                h = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(h)) == 0:
                    self.lib, self.handle = lib, h
        except OSError:
            pass

    def temp(self) -> float | None:
        if not self.lib:
            return None
        t = ctypes.c_uint()
        return float(t.value) if self.lib.nvmlDeviceGetTemperature(self.handle, 0, ctypes.byref(t)) == 0 else None


# ---------------------------------------------------------------- face

def hex_rgb(s: str) -> tuple[int, int, int]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


class TempFace:
    """Black dial, a conic gradient ring, CPU and GPU temperatures stacked."""

    def __init__(self, start: str, end: str):
        self.big = ImageFont.truetype(FONT_BOLD, 112)
        self.unit = ImageFont.truetype(FONT_REGULAR, 40)
        self.label = ImageFont.truetype(FONT_BOLD, 30)
        self.base = self._ring(hex_rgb(start), hex_rgb(end))

    @staticmethod
    def _ring(a, b) -> Image.Image:
        img = Image.new("RGB", (SIZE, SIZE), "black")
        d = ImageDraw.Draw(img)
        m, w = 14, 26
        for deg in range(360):
            # gradient goes a -> b -> a around the ring so there is no seam
            t = 1 - abs((deg / 360) * 2 - 1)
            col = tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))
            d.arc((m, m, SIZE - m, SIZE - m), deg - 90, deg - 89 + 1, fill=col, width=w)
        d.line((120, SIZE // 2, SIZE - 120, SIZE // 2), fill=(70, 70, 70), width=3)
        return img

    def render(self, cpu: float | None, gpu: float | None) -> Image.Image:
        img = self.base.copy()
        d = ImageDraw.Draw(img)
        for label, value, y in (("CPU", cpu, 150), ("GPU", gpu, 348)):
            d.text((SIZE // 2, y - 80), label, font=self.label, fill=(170, 170, 170), anchor="mm")
            text = "--" if value is None else f"{value:.0f}"
            d.text((SIZE // 2 - 12, y + 6), text, font=self.big, fill="white", anchor="mm")
            right = d.textbbox((SIZE // 2 - 12, y + 6), text, font=self.big, anchor="mm")[2]
            d.text((right + 6, y - 28), "°C", font=self.unit, fill=(200, 200, 200), anchor="lm")
        return img


# ---------------------------------------------------------------- commands

def run(args):
    face = TempFace(args.ring_start, args.ring_end)
    gpu = NvidiaGPU()
    stop = False

    def on_signal(*_):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    lcd, last, last_sent = None, None, 0.0
    while not stop:
        try:
            if lcd is None:
                lcd = LCD(args.device)
                if args.brightness is not None:
                    lcd.brightness(args.brightness)
                last = None
            reading = (cpu_temp(), gpu.temp())
            shown = tuple(None if v is None else round(v) for v in reading)
            if shown != last or time.monotonic() - last_sent > 30:
                lcd.frame(face.render(*shown), args.rotate)
                last, last_sent = shown, time.monotonic()
        except OSError as e:  # unplugged, suspended, or not there yet: retry
            print(f"omen-lcd: {e}; retrying", file=sys.stderr, flush=True)
            if lcd:
                try:
                    lcd.close()
                except OSError:
                    pass
            lcd = None
            time.sleep(5)
            continue
        time.sleep(args.interval)

    # Don't leave stale temperatures on screen.
    if lcd:
        try:
            lcd.frame(Image.new("RGB", (SIZE, SIZE), "black"))
        except OSError:
            pass


def main():
    p = argparse.ArgumentParser(prog="omen-lcd", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", help="hidraw node (default: auto-detect)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    b = sub.add_parser("brightness"); b.add_argument("level", type=int)
    i = sub.add_parser("image"); i.add_argument("file"); i.add_argument("--rotate", type=int, default=90)
    r = sub.add_parser("run")
    r.add_argument("--rotate", type=int, default=90, help="clockwise degrees (this pump is mounted needing 90)")
    r.add_argument("--interval", type=float, default=2.0, help="seconds between sensor reads")
    r.add_argument("--brightness", type=int, help="set brightness 0-100 at start")
    r.add_argument("--ring-start", default="#e040fb", help="ring gradient colour (top)")
    r.add_argument("--ring-end", default="#00e5ff", help="ring gradient colour (bottom)")
    a = p.parse_args()

    if a.cmd == "run":
        return run(a)
    lcd = LCD(a.device)
    if a.cmd == "info":
        print("\n".join(lcd.info()))
    elif a.cmd == "brightness":
        lcd.brightness(a.level)
    elif a.cmd == "image":
        lcd.frame(Image.open(a.file), a.rotate)


if __name__ == "__main__":
    main()
