# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""A QR code of a short text, drawn as SVG, for the pairing page.

The encoder follows ISO/IEC 18004: byte mode, the smallest version that holds
the text, the highest error correction that fits that version at no cost, and
the mask of the lowest penalty. It uses the standard library alone. Its output
is checked module for module against ``qrcodegen`` in the tests.

The picture is one path of the dark modules on a white square, with a quiet
zone of four modules. It holds no script and no external reference.
"""

from __future__ import annotations

from collections import deque
from enum import IntEnum

QUIET_MODULES = 4


class Ecc(IntEnum):
    """An error correction level; the value is its index in the tables."""

    LOW = 0
    MEDIUM = 1
    QUARTILE = 2
    HIGH = 3


_FORMAT_BITS = {Ecc.LOW: 1, Ecc.MEDIUM: 0, Ecc.QUARTILE: 3, Ecc.HIGH: 2}

# Per level, per version (index 0 unused).
_ECC_CODEWORDS_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28,
     28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30,
     30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26,
     26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28,
     28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28,
     26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30,
     30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28,
     26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30,
     30, 30, 30),
)  # fmt: skip
_ERROR_CORRECTION_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10,
     12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17,
     18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23,
     23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25,
     34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
)  # fmt: skip

_PENALTY_RUN = 3
_PENALTY_BLOCK = 3
_PENALTY_FINDER = 40
_PENALTY_BALANCE = 10


class QrTooLongError(ValueError):
    """The text does not fit in a QR code of version 40."""


def _raw_modules(version: int) -> int:
    """The modules of a version left for data and error correction."""
    result = (16 * version + 128) * version + 64
    if version >= 2:
        aligns = version // 7 + 2
        result -= (25 * aligns - 10) * aligns - 55
        if version >= 7:
            result -= 36
    return result


def _data_codewords(version: int, ecc: Ecc) -> int:
    return (
        _raw_modules(version) // 8
        - _ECC_CODEWORDS_PER_BLOCK[ecc][version]
        * _ERROR_CORRECTION_BLOCKS[ecc][version]
    )


def _segment_bits(length: int, version: int) -> int:
    """Byte mode: the mode, the count, and eight bits a byte."""
    return 4 + (8 if version <= 9 else 16) + 8 * length


def _multiply(x: int, y: int) -> int:
    """The product in GF(2^8) modulo x^8 + x^4 + x^3 + x^2 + 1."""
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree: int) -> list[int]:
    result = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _multiply(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _multiply(root, 0x02)
    return result


def _remainder(data: list[int], divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(divisor):
            result[i] ^= _multiply(coefficient, factor)
    return result


def _bit(value: int, index: int) -> bool:
    return (value >> index) & 1 != 0


class QrCode:
    """The modules of a QR code: ``modules[y][x]`` is dark when true."""

    def __init__(self, data: bytes, ecc: Ecc = Ecc.MEDIUM) -> None:
        version = next(
            (
                v
                for v in range(1, 41)
                if _segment_bits(len(data), v) <= _data_codewords(v, ecc) * 8
            ),
            None,
        )
        if version is None:
            raise QrTooLongError(f"{len(data)} bytes do not fit in a QR code")
        used = _segment_bits(len(data), version)
        for better in (Ecc.MEDIUM, Ecc.QUARTILE, Ecc.HIGH):
            if better > ecc and used <= _data_codewords(version, better) * 8:
                ecc = better
        self.version = version
        self.ecc = ecc
        self.size = version * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self._function = [[False] * self.size for _ in range(self.size)]
        self._draw_function_patterns()
        self._draw_codewords(self._interleaved(self._codewords(data)))
        best, lowest = 0, -1
        for mask in range(8):
            self._apply_mask(mask)
            self._draw_format(mask)
            penalty = self._penalty()
            if lowest < 0 or penalty < lowest:
                best, lowest = mask, penalty
            self._apply_mask(mask)  # the mask is its own inverse
        self.mask = best
        self._apply_mask(best)
        self._draw_format(best)

    def _codewords(self, data: bytes) -> list[int]:
        bits: list[int] = []

        def append(value: int, length: int) -> None:
            bits.extend((value >> i) & 1 for i in reversed(range(length)))

        append(0b0100, 4)
        append(len(data), 8 if self.version <= 9 else 16)
        for byte in data:
            append(byte, 8)
        capacity = _data_codewords(self.version, self.ecc) * 8
        append(0, min(4, capacity - len(bits)))
        append(0, -len(bits) % 8)
        pad = 0xEC
        while len(bits) < capacity:
            append(pad, 8)
            pad ^= 0xEC ^ 0x11
        return [
            int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits), 8)
        ]

    def _interleaved(self, data: list[int]) -> list[int]:
        blocks_count = _ERROR_CORRECTION_BLOCKS[self.ecc][self.version]
        ecc_length = _ECC_CODEWORDS_PER_BLOCK[self.ecc][self.version]
        raw = _raw_modules(self.version) // 8
        short_blocks = blocks_count - raw % blocks_count
        short_length = raw // blocks_count
        divisor = _divisor(ecc_length)
        blocks: list[list[int]] = []
        start = 0
        for i in range(blocks_count):
            length = short_length - ecc_length + (0 if i < short_blocks else 1)
            block = data[start : start + length]
            start += length
            ecc = _remainder(block, divisor)
            if i < short_blocks:
                block.append(0)  # a place the interleaving skips
            blocks.append(block + ecc)
        result: list[int] = []
        for i in range(len(blocks[0])):
            for j, block in enumerate(blocks):
                if i != short_length - ecc_length or j >= short_blocks:
                    result.append(block[i])
        return result

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self._function[y][x] = True

    def _alignment_positions(self) -> list[int]:
        if self.version == 1:
            return []
        aligns = self.version // 7 + 2
        step = (self.version * 8 + aligns * 3 + 5) // (aligns * 4 - 4) * 2
        return [6, *reversed([self.size - 7 - i * step for i in range(aligns - 1)])]

    def _draw_function_patterns(self) -> None:
        size = self.size
        for i in range(size):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (size - 4, 3), (3, size - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < size and 0 <= y < size:
                        self._set(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        positions = self._alignment_positions()
        last = len(positions) - 1
        for i, px in enumerate(positions):
            for j, py in enumerate(positions):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(px + dx, py + dy, max(abs(dx), abs(dy)) != 1)
        self._draw_format(0)
        if self.version >= 7:
            remainder = self.version
            for _ in range(12):
                remainder = (remainder << 1) ^ ((remainder >> 11) * 0x1F25)
            bits = self.version << 12 | remainder
            for i in range(18):
                a, b = size - 11 + i % 3, i // 3
                self._set(a, b, _bit(bits, i))
                self._set(b, a, _bit(bits, i))

    def _draw_format(self, mask: int) -> None:
        data = _FORMAT_BITS[self.ecc] << 3 | mask
        remainder = data
        for _ in range(10):
            remainder = (remainder << 1) ^ ((remainder >> 9) * 0x537)
        bits = (data << 10 | remainder) ^ 0x5412
        size = self.size
        for i in range(6):
            self._set(8, i, _bit(bits, i))
        self._set(8, 7, _bit(bits, 6))
        self._set(8, 8, _bit(bits, 7))
        self._set(7, 8, _bit(bits, 8))
        for i in range(9, 15):
            self._set(14 - i, 8, _bit(bits, i))
        for i in range(8):
            self._set(size - 1 - i, 8, _bit(bits, i))
        for i in range(8, 15):
            self._set(8, size - 15 + i, _bit(bits, i))
        self._set(8, size - 8, True)

    def _draw_codewords(self, data: list[int]) -> None:
        size = self.size
        i = 0
        right = size - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = (right + 1) & 2 == 0
            for vertical in range(size):
                y = size - 1 - vertical if upward else vertical
                for j in range(2):
                    x = right - j
                    if not self._function[y][x] and i < len(data) * 8:
                        self.modules[y][x] = _bit(data[i >> 3], 7 - (i & 7))
                        i += 1
            right -= 2

    def _apply_mask(self, mask: int) -> None:
        for y in range(self.size):
            row, function = self.modules[y], self._function[y]
            for x in range(self.size):
                if not function[x] and _masked(mask, x, y):
                    row[x] = not row[x]

    def _penalty(self) -> int:
        size = self.size
        result = 0
        lines = [
            *self.modules,
            *([row[x] for row in self.modules] for x in range(size)),
        ]
        for line in lines:
            color, run = False, 0
            history: deque[int] = deque([0] * 7, 7)
            for dark in line:
                if dark == color:
                    run += 1
                    if run == 5:
                        result += _PENALTY_RUN
                    elif run > 5:
                        result += 1
                else:
                    self._add_history(run, history)
                    if not color:
                        result += self._finder_like(history) * _PENALTY_FINDER
                    color, run = dark, 1
            if color:
                self._add_history(run, history)
                run = 0
            self._add_history(run + size, history)
            result += self._finder_like(history) * _PENALTY_FINDER
        for y in range(size - 1):
            for x in range(size - 1):
                dark = self.modules[y][x]
                if (
                    dark
                    == self.modules[y][x + 1]
                    == self.modules[y + 1][x]
                    == self.modules[y + 1][x + 1]
                ):
                    result += _PENALTY_BLOCK
        dark_count = sum(row.count(True) for row in self.modules)
        total = size * size
        k = (abs(dark_count * 20 - total * 10) + total - 1) // total - 1
        return result + k * _PENALTY_BALANCE

    def _add_history(self, run: int, history: deque[int]) -> None:
        if history[0] == 0:
            run += self.size  # the light border before the first run
        history.appendleft(run)

    @staticmethod
    def _finder_like(history: deque[int]) -> int:
        n = history[1]
        core = (
            n > 0
            and history[2] == history[4] == history[5] == n
            and history[3] == n * 3
        )
        return int(core and history[0] >= n * 4 and history[6] >= n) + int(
            core and history[6] >= n * 4 and history[0] >= n
        )


def _masked(mask: int, x: int, y: int) -> bool:
    match mask:
        case 0:
            return (x + y) % 2 == 0
        case 1:
            return y % 2 == 0
        case 2:
            return x % 3 == 0
        case 3:
            return (x + y) % 3 == 0
        case 4:
            return (x // 3 + y // 2) % 2 == 0
        case 5:
            return x * y % 2 + x * y % 3 == 0
        case 6:
            return (x * y % 2 + x * y % 3) % 2 == 0
        case _:
            return ((x + y) % 2 + x * y % 3) % 2 == 0


def qr_svg(text: str) -> str:
    """``text`` as a QR code in SVG: one path of the dark modules, and a quiet
    zone of four."""
    qr = QrCode(text.encode("utf-8"))
    full = qr.size + 2 * QUIET_MODULES
    dark = "".join(
        f"M{x + QUIET_MODULES} {y + QUIET_MODULES}h1v1h-1z"
        for y in range(qr.size)
        for x in range(qr.size)
        if qr.modules[y][x]
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {full} {full}"'
        ' shape-rendering="crispEdges">'
        f'<rect width="{full}" height="{full}" fill="#fff"/>'
        f'<path d="{dark}" fill="#000"/>'
        "</svg>"
    )
