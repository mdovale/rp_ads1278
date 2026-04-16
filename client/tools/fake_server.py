from __future__ import annotations

import argparse
import math
import socket
import time

from ads1278_client.models import CommandOpcode, MessageType
from ads1278_client.protocol import (
    CAPABILITY_LINE,
    SERVER_PORT,
    build_message,
    unpack_command,
)


class FakeAds1278Server:
    def __init__(self, sample_period: float, demo_sequence: bool) -> None:
        self.sample_period = sample_period
        self.demo_sequence = demo_sequence
        self.enabled = False
        self.frame_cnt = 0
        self.msg_seq = 0
        self.extclk_div = 625
        self.phase = 0.0

    def serve(self, host: str, port: int) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((host, port))
        server.listen(1)
        print(f"fake server listening on {host}:{port}")
        while True:
            conn, addr = server.accept()
            print(f"client connected from {addr[0]}:{addr[1]}")
            try:
                self.handle_client(conn)
            except Exception as exc:
                print(f"client session ended: {exc}")
            finally:
                conn.close()

    def handle_client(self, conn: socket.socket) -> None:
        conn.settimeout(0.05)
        conn.sendall(f"{CAPABILITY_LINE}\n".encode("ascii"))
        conn.sendall(self.make_message(MessageType.SAMPLE, 0, 0))

        if self.demo_sequence:
            conn.sendall(
                self.make_message(
                    MessageType.ACK,
                    CommandOpcode.SET_ENABLE,
                    1,
                )
            )
            conn.sendall(
                self.make_message(
                    MessageType.ERROR,
                    CommandOpcode.SET_EXTCLK_DIV,
                    2,
                )
            )

        next_emit = time.monotonic() + self.sample_period
        while True:
            now = time.monotonic()
            if self.enabled and now >= next_emit:
                self.frame_cnt = (self.frame_cnt + 1) & 0xFFFF
                conn.sendall(self.make_message(MessageType.SAMPLE, 0, 0))
                next_emit = now + self.sample_period

            try:
                payload = conn.recv(8)
            except socket.timeout:
                continue

            if not payload:
                return
            if len(payload) != 8:
                raise ConnectionError("short command")

            opcode, value = unpack_command(payload)
            if opcode == CommandOpcode.SET_ENABLE and value in (0, 1):
                self.enabled = bool(value)
                conn.sendall(self.make_message(MessageType.ACK, opcode, value))
                continue

            if opcode == CommandOpcode.TRIGGER_SYNC:
                conn.sendall(self.make_message(MessageType.ACK, opcode, value))
                continue

            if opcode == CommandOpcode.MARK_CAPTURE:
                conn.sendall(self.make_message(MessageType.ACK, opcode, value))
                continue

            if opcode == CommandOpcode.SET_EXTCLK_DIV and value >= 3:
                self.extclk_div = value
                conn.sendall(self.make_message(MessageType.ACK, opcode, value))
                continue

            conn.sendall(self.make_message(MessageType.ERROR, opcode, value))

    def make_message(self, msg_type: MessageType, opcode: int, value: int) -> bytes:
        self.msg_seq += 1
        channels = []
        for idx in range(8):
            wave = math.sin(self.phase + idx * 0.4)
            amplitude = 500_000 + idx * 25_000
            sample = int(amplitude * wave)
            if idx % 3 == 1:
                sample *= -1
            channels.append(sample)
        self.phase += 0.15

        status_raw = (self.frame_cnt << 16) | 0x1
        if self.frame_cnt and self.frame_cnt % 25 == 0:
            status_raw |= 0x2
        ctrl_raw = 0x2 if self.enabled else 0x0

        return build_message(
            msg_type,
            self.msg_seq,
            opcode,
            value,
            status_raw,
            ctrl_raw,
            self.extclk_div,
            channels,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fake rp_ads1278 TCP server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=SERVER_PORT)
    parser.add_argument("--sample-period", type=float, default=0.1)
    parser.add_argument(
        "--demo-sequence",
        action="store_true",
        help="Send one ACK and one ERROR immediately after connect",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    FakeAds1278Server(
        sample_period=args.sample_period,
        demo_sequence=args.demo_sequence,
    ).serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
