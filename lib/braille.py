#!/usr/bin/env python3
"""Braille-cell canvas: 2x4 dots per character. Pure stdlib.

A terminal cell holding one braille glyph addresses eight independent dots, so
a plot gets twice the horizontal and four times the vertical resolution of one
character per point. That is the difference between a curve you can read the
shape of and a row of asterisks.

Dot bit layout (Unicode braille patterns, U+2800 + mask):

    1 4      0x01 0x08
    2 5      0x02 0x10
    3 6      0x04 0x20
    7 8      0x40 0x80
"""
BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


class Canvas:
    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.w, self.h = cols * 2, rows * 4      # dot resolution
        self.cells = [[0] * cols for _ in range(rows)]

    def dot(self, x, y):
        if not (0 <= x < self.w and 0 <= y < self.h):
            return
        self.cells[y // 4][x // 2] |= BITS[y % 4][x % 2]

    def line(self, x0, y0, x1, y1):
        """Bresenham, so a steep segment stays connected."""
        dx, dy = abs(x1 - x0), -abs(y1 - y0)
        sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
        err = dx + dy
        while True:
            self.dot(x0, y0)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def plot(self, values):
        """values: one y (in dot space) per dot-column, None to break the line."""
        prev = None
        for x, y in enumerate(values):
            if y is None:
                prev = None
                continue
            if prev is not None:
                self.line(x - 1, prev, x, y)
            else:
                self.dot(x, y)
            prev = y

    def rows_text(self):
        return ["".join(chr(0x2800 + c) for c in row) for row in self.cells]
