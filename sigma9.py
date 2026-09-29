"""Sigma-9 greeting for every Gravity app.

Derivatives 1, 2, 3, 3. The repeated H carries the last 3 because 1+2+3 is 6.
The sum is 9 and 9 is the maximum. The GRAVITY prologue is those 9 bytes.
"""

from __future__ import annotations

import socket

DERIV = (1, 2, 3, 3)
PROLOGUE = b"GRAVITY\x00\x01"
MAX = 9


def sigma() -> int:
    total = 0
    for d in DERIV:
        if d < 1 or d > MAX or total + d > MAX:
            raise ValueError(f"derivative {d} breaks sigma max {MAX}")
        total += d
    if total != MAX:
        raise ValueError(f"sigma {total} != {MAX}")
    return total


def check_prologue(buf: bytes) -> None:
    if buf != PROLOGUE or len(buf) != sigma():
        raise ValueError("bad gravity prologue")


def _read_exact(sock: socket.socket, n: int) -> bytes:
    prev = sock.gettimeout()
    if prev is None:
        sock.settimeout(2.0)
    try:
        buf = bytearray()
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionResetError("gravity handshake closed")
            buf += chunk
        return bytes(buf)
    finally:
        sock.settimeout(prev)


def read_sigma9(sock: socket.socket, n: int) -> bytes:
    """Read n bytes. The first 9 follow derivatives 1+2+3+3. Bytes past 9 do not raise the sum."""
    if n < 0:
        raise ValueError("negative read")
    out = bytearray()
    total = 0
    for d in DERIV:
        if d < 1 or d > MAX or total + d > MAX:
            raise ValueError(f"derivative {d} breaks sigma max {MAX}")
        take = min(d, n - len(out))
        if take:
            out += _read_exact(sock, take)
        total += d
    if total != sigma():
        raise ValueError(f"sigma {total} != 9")
    if len(out) < n:
        out += _read_exact(sock, n - len(out))
    return bytes(out)
