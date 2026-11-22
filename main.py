#!/usr/bin/env python3
"""news-image-20261122 -- "Four Fronts".

A one-day newspaper front page that sums up the world news of
Sunday 22 November 2026 in a single 1024x1024 image.

Drawn entirely with the Python standard library: a small software
canvas (rectangles, lines, circles, polygons), a hand-written 5x7
bitmap font, and a pure-Python PNG encoder (signature, IHDR, zlib
IDAT, IEND, CRC32). No network, no randomness, no clock -- the
program is fully deterministic and writes the same bytes on every run.

Stories (all reported on 22 November 2026):
  1. Mexico -- FBI most-wanted cartel boss "El Chapo Isidro" captured
     in Sinaloa after a gunfight that left 11 dead.
  2. Ukraine / Poland -- Russian strike on Kryvyi Rih killed 2 and
     wounded 60; two missiles and a drone came down in Poland; NATO
     vowed to defend every inch of Polish territory.
  3. Israel -- President Herzog asked ex-army chief Gadi Eisenkot to
     try to form the next government, bypassing PM Netanyahu.
  4. United States -- FBI investigating an apparent hack of its
     National Crime Information Center database.
Plus a footer strip: COP31 talks deadlocked, Norway court voids
disputed oil licences, Myanmar shaken by a 4.1 quake.
"""

import os
import struct
import zlib
from binascii import crc32

W, H = 1024, 1024

# ---------------------------------------------------------------- palette
PAPER = (246, 241, 227)   # newsprint cream
INK = (26, 26, 26)       # near-black ink
RED = (178, 38, 30)      # headline red
NAVY = (20, 50, 79)      # panel 2 band / night sky
TEAL = (14, 107, 92)     # panel 3 band
OCHRE = (192, 122, 26)   # panel 4 band / sun
SAND = (224, 205, 160)   # desert ground
BROWN = (122, 74, 38)    # mountains
GREEN = (46, 110, 58)    # cactus
SKYBLUE = (74, 125, 214) # shield
GOLD = (232, 178, 44)    # explosion / warning
WHITE = (255, 255, 255)
GREY = (90, 90, 84)
LIGHTBLUE = (158, 196, 232)
DARKBLUE = (28, 52, 96)


# ------------------------------------------------------------------ canvas
class Canvas:
    """An RGB canvas with simple vector drawing primitives."""

    def __init__(self, w, h, bg):
        self.w = w
        self.h = h
        self.px = bytearray(bytes(bg) * (w * h))

    def set(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.px[i] = c[0]
            self.px[i + 1] = c[1]
            self.px[i + 2] = c[2]

    def rect(self, x, y, w, h, c):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        row = bytes(c) * (x1 - x0)
        for yy in range(y0, y1):
            i = (yy * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def hline(self, x0, x1, y, c, thick=1):
        for t in range(thick):
            self.rect(min(x0, x1), y + t, abs(x1 - x0) + 1, 1, c)

    def vline(self, x, y0, y1, c, thick=1):
        for t in range(thick):
            self.rect(x + t, min(y0, y1), 1, abs(y1 - y0) + 1, c)

    def line(self, x0, y0, x1, y1, c, thick=1):
        """Bresenham line, with optional thickness."""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        x, y = x0, y0
        while True:
            self.rect(x - thick // 2, y - thick // 2, thick, thick, c)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x += sx
            if e2 <= dx:
                err += dx
                y += sy

    def circle(self, cx, cy, r, c):
        """Filled circle."""
        for dy in range(-r, r + 1):
            half = int((r * r - dy * dy) ** 0.5)
            self.rect(cx - half, cy + dy, half * 2 + 1, 1, c)

    def ring(self, cx, cy, r, c, thick=2):
        for dy in range(-r, r + 1):
            half = int((r * r - dy * dy) ** 0.5)
            inner = int(max(0, (r - thick) ** 2 - dy * dy) ** 0.5) \
                if abs(dy) < r - thick else 0
            self.rect(cx - half, cy + dy, half - inner, 1, c)
            self.rect(cx + inner + 1, cy + dy, half - inner, 1, c)

    def ellipse(self, cx, cy, rx, ry, c):
        for dy in range(-ry, ry + 1):
            t = 1.0 - (dy * dy) / float(ry * ry)
            half = int(rx * (t ** 0.5)) if t > 0 else 0
            self.rect(cx - half, cy + dy, half * 2 + 1, 1, c)

    def polygon(self, pts, c):
        """Filled polygon (even-odd scanline fill)."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        for y in range(min(ys), max(ys) + 1):
            xs = []
            n = len(pts)
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    t = (y - y0) / float(y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                self.rect(int(xs[i]), y, int(xs[i + 1]) - int(xs[i]) + 1, 1, c)

    def triangle(self, x0, y0, x1, y1, x2, y2, c):
        self.polygon([(x0, y0), (x1, y1), (x2, y2)], c)


# -------------------------------------------------------------- PNG output
def png_bytes(cv):
    """Encode the canvas as a PNG (color type 2, 8-bit, filter 0)."""
    raw = bytearray()
    stride = cv.w * 3
    for y in range(cv.h):
        raw.append(0)
        raw += cv.px[y * stride:(y + 1) * stride]
    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        out = struct.pack(">I", len(data)) + tag + data
        out += struct.pack(">I", crc32(tag + data) & 0xFFFFFFFF)
        return out

    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", comp)
            + chunk(b"IEND", b""))


# ------------------------------------------------------- 5x7 bitmap font
# Each glyph is 7 rows of 5 pixels; "#" is on, "." is off.
# Hand-written for this entry: capitals, digits and punctuation only;
# all text in the image is set in capitals.
FONT = {
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "G": (".####", "#....", "#....", "#.###", "#...#", "#...#", ".###."),
    "H": ("#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "J": ("..###", "...#.", "...#.", "...#.", "...#.", "#..#.", ".##.."),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "V": ("#...#", "#...#", "#...#", "#...#", "#...#", ".#.#.", "..#.."),
    "W": ("#...#", "#...#", "#...#", "#.#.#", "#.#.#", "##.##", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Y": ("#...#", "#...#", ".#.#.", "..#..", "..#..", "..#..", "..#.."),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
    "0": (".###.", "#..##", "#.#.#", "##..#", "#...#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "5": ("#####", "#....", "####.", "....#", "....#", "#...#", ".###."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    ",": (".....", ".....", ".....", ".....", ".##..", ".##..", ".#..."),
    "-": (".....", ".....", ".....", ".###.", ".....", ".....", "....."),
    ":": (".....", ".##..", ".##..", ".....", ".##..", ".##..", "....."),
    "!": ("..#..", "..#..", "..#..", "..#..", "..#..", ".....", "..#.."),
    "?": (".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."),
    "'": ("..#..", "..#..", ".....", ".....", ".....", ".....", "....."),
    '"': (".#.#.", ".#.#.", ".....", ".....", ".....", ".....", "....."),
    "(": ("...#.", "..#..", ".#...", ".#...", ".#...", "..#..", "...#."),
    ")": (".#...", "..#..", "...#.", "...#.", "...#.", "..#..", ".#..."),
    "/": ("....#", "....#", "...#.", "..#..", ".#...", "#....", "#...."),
    "|": ("..#..", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "$": ("..#..", ".####", "#.#..", ".###.", "..#.#", "####.", "..#.."),
    ";": (".....", ".##..", ".##..", ".....", ".##..", ".##..", ".#..."),
}


def text_width(s, scale, spacing=1):
    """Pixel width of a string at the given scale."""
    return len(s) * (5 + spacing) * scale - spacing * scale


def draw_text(cv, x, y, s, scale, color, spacing=1):
    """Draw a string with the 5x7 font; returns the x after the text."""
    s = s.upper()
    cx = x
    adv = (5 + spacing) * scale
    for ch in s:
        glyph = FONT.get(ch)
        if glyph is not None:
            for r, row in enumerate(glyph):
                for col, px in enumerate(row):
                    if px == "#":
                        cv.rect(cx + col * scale, y + r * scale,
                                scale, scale, color)
        cx += adv
    return cx


def draw_text_centered(cv, cx, y, s, scale, color, spacing=1):
    draw_text(cv, cx - text_width(s, scale, spacing) // 2,
              y, s, scale, color, spacing)


def wrap_text(s, max_w, scale, spacing=1):
    """Greedy word wrap; returns a list of lines."""
    lines = []
    cur = ""
    for word in s.split(" "):
        trial = (cur + " " + word) if cur else word
        if text_width(trial, scale, spacing) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


# ------------------------------------------------------------ illustration
import math


def star_points(cx, cy, r_out, r_in, spikes):
    """Points of a spiky star, alternating outer/inner radius."""
    pts = []
    for i in range(spikes * 2):
        r = r_out if i % 2 == 0 else r_in
        a = -math.pi / 2 + i * math.pi / spikes
        pts.append((int(cx + r * math.cos(a)), int(cy + r * math.sin(a))))
    return pts


def scene_mexico(cv, ix, iy, iw, ih):
    """Desert, mountains, cactus and a helicopter over Sinaloa."""
    cv.circle(ix + 398, iy + 26, 18, OCHRE)
    cv.polygon([(ix, iy + ih), (ix + 80, iy + 42), (ix + 170, iy + ih)], BROWN)
    cv.polygon([(ix + 120, iy + ih), (ix + 220, iy + 58),
                (ix + 330, iy + ih)], (96, 58, 32))
    cv.rect(ix, iy + 90, iw, ih - 90, SAND)
    # cactus
    cv.rect(ix + 28, iy + 58, 10, 60, GREEN)
    cv.rect(ix + 14, iy + 78, 14, 8, GREEN)
    cv.rect(ix + 14, iy + 70, 8, 16, GREEN)
    cv.rect(ix + 38, iy + 88, 14, 8, GREEN)
    cv.rect(ix + 44, iy + 80, 8, 16, GREEN)
    # helicopter
    hx, hy = ix + 250, iy + 34
    cv.line(hx - 42, hy - 16, hx + 48, hy - 16, INK, 3)
    cv.line(hx, hy - 16, hx, hy - 10, INK, 2)
    cv.ellipse(hx, hy, 30, 11, INK)
    cv.polygon([(hx + 26, hy - 6), (hx + 66, hy - 14),
                (hx + 66, hy - 4), (hx + 26, hy + 6)], INK)
    cv.triangle(hx + 58, hy - 14, hx + 66, hy - 26, hx + 66, hy - 12, INK)
    cv.line(hx - 22, hy + 18, hx + 22, hy + 18, INK, 2)
    cv.line(hx - 16, hy + 11, hx - 20, hy + 18, INK, 2)
    cv.line(hx + 16, hy + 11, hx + 20, hy + 18, INK, 2)
    cv.line(hx - 78, hy - 4, hx - 58, hy - 4, GREY, 2)
    cv.line(hx - 84, hy + 6, hx - 66, hy + 6, GREY, 2)
    # roadblock flame
    cv.polygon([(ix + 375, iy + 90), (ix + 385, iy + 64),
                (ix + 395, iy + 90)], GOLD)
    cv.polygon([(ix + 380, iy + 90), (ix + 385, iy + 74),
                (ix + 390, iy + 90)], RED)


def scene_ukraine(cv, ix, iy, iw, ih):
    """Night sky, incoming missiles, explosion and a shield."""
    cv.rect(ix, iy, iw, ih, NAVY)
    for sx, sy in [(30, 12), (80, 30), (140, 8), (200, 22), (260, 10),
                   (330, 26), (410, 12), (440, 40), (60, 55), (380, 60),
                   (230, 46), (20, 84)]:
        cv.rect(ix + sx, iy + sy, 2, 2, WHITE)
    # explosion starburst
    cv.polygon(star_points(ix + 120, iy + 66, 36, 15, 8), GOLD)
    cv.polygon(star_points(ix + 120, iy + 66, 20, 8, 8), (240, 90, 30))
    cv.circle(ix + 120, iy + 66, 7, WHITE)
    # missile trails arcing in from the right
    cv.line(ix + 310, iy + 12, ix + 158, iy + 52, WHITE, 2)
    cv.circle(ix + 312, iy + 12, 4, GOLD)
    cv.line(ix + 372, iy + 42, ix + 172, iy + 74, LIGHTBLUE, 2)
    cv.circle(ix + 374, iy + 42, 4, GOLD)
    cv.line(ix + 250, iy + 30, ix + 200, iy + 44, WHITE, 1)
    # shield (defence) at lower right
    shx, shy = ix + 385, iy + 46
    cv.polygon([(shx, shy), (shx + 44, shy), (shx + 44, shy + 26),
                (shx + 22, shy + 50), (shx, shy + 26)], SKYBLUE)
    cv.polygon(star_points(shx + 22, shy + 22, 11, 4, 4), WHITE)


def scene_israel(cv, ix, iy, iw, ih):
    """Parliament building with dome, flag and ballot box."""
    # ballot box at left
    cv.rect(ix + 36, iy + 82, 56, 36, TEAL)
    cv.rect(ix + 46, iy + 82, 36, 4, INK)
    cv.line(ix + 48, iy + 100, ix + 58, iy + 110, WHITE, 3)
    cv.line(ix + 58, iy + 110, ix + 80, iy + 92, WHITE, 3)
    # dome first, so the building covers its lower half
    cv.circle(ix + 230, iy + 62, 30, TEAL)
    # building
    cv.rect(ix + 130, iy + 66, 200, 52, (222, 208, 176))
    cv.rect(ix + 120, iy + 60, 220, 8, (190, 172, 136))
    for cx in (145, 181, 217, 253, 289):
        cv.rect(ix + cx, iy + 76, 8, 42, INK)
    cv.rect(ix + 218, iy + 96, 24, 22, INK)
    # dome finial above the roofline
    cv.line(ix + 230, iy + 32, ix + 230, iy + 22, TEAL, 2)
    cv.circle(ix + 230, iy + 20, 3, GOLD)
    # flag at right
    cv.line(ix + 386, iy + 26, ix + 386, iy + 92, INK, 2)
    cv.rect(ix + 386, iy + 26, 46, 26, WHITE)
    cv.rect(ix + 386, iy + 30, 46, 4, SKYBLUE)
    cv.rect(ix + 386, iy + 44, 46, 4, SKYBLUE)
    cv.polygon(star_points(ix + 409, iy + 39, 7, 3, 6), SKYBLUE)


def scene_fbi(cv, ix, iy, iw, ih):
    """A monitor showing a database and a warning triangle."""
    cv.rect(ix, iy + 96, iw, ih - 96, (200, 192, 170))
    # monitor
    cv.rect(ix + 150, iy + 12, 200, 80, INK)
    cv.rect(ix + 158, iy + 20, 184, 64, DARKBLUE)
    cv.rect(ix + 244, iy + 92, 12, 6, INK)
    cv.rect(ix + 224, iy + 98, 52, 5, INK)
    # window dots
    cv.circle(ix + 168, iy + 28, 3, RED)
    cv.circle(ix + 180, iy + 28, 3, GOLD)
    cv.circle(ix + 192, iy + 28, 3, GREEN)
    # database cylinder on screen
    cv.rect(ix + 180, iy + 44, 44, 34, LIGHTBLUE)
    cv.ellipse(ix + 202, iy + 44, 22, 7, WHITE)
    cv.ellipse(ix + 202, iy + 78, 22, 7, LIGHTBLUE)
    cv.hline(ix + 184, ix + 220, iy + 56, WHITE, 2)
    cv.hline(ix + 184, ix + 220, iy + 66, WHITE, 2)
    # warning triangle
    cv.polygon([(ix + 300, iy + 34), (ix + 334, iy + 80),
                (ix + 266, iy + 80)], GOLD)
    cv.rect(ix + 298, iy + 50, 4, 16, INK)
    cv.rect(ix + 298, iy + 70, 4, 4, INK)


# ------------------------------------------------------------------- layout
PW, PH = 480, 330
PANELS = [
    {
        "num": "1", "region": "MEXICO", "band": RED,
        "headline": "CARTEL BOSS 'EL CHAPO ISIDRO' CAPTURED",
        "body": "MEXICAN SPECIAL FORCES SEIZED FBI MOST-WANTED "
                "FAUSTO ISIDRO MEZA FLORES IN SINALOA. A GUNFIGHT "
                "LEFT 11 DEAD. HE WAS FLOWN TO MEXICO CITY.",
        "scene": scene_mexico,
    },
    {
        "num": "2", "region": "UKRAINE AND POLAND", "band": NAVY,
        "headline": "WAR SPILLS OVER: MISSILES LAND IN POLAND",
        "body": "A RUSSIAN STRIKE ON ZELENSKYY'S HOMETOWN KILLED 2 "
                "AND WOUNDED 60. TWO MISSILES AND A DRONE CAME DOWN "
                "IN POLAND. NATO VOWED TO DEFEND EVERY INCH OF POLAND.",
        "scene": scene_ukraine,
    },
    {
        "num": "3", "region": "ISRAEL", "band": TEAL,
        "headline": "EISENKOT TAPPED TO FORM ISRAEL'S NEXT GOVERNMENT",
        "body": "PRESIDENT HERZOG ASKED EX-ARMY CHIEF GADI EISENKOT "
                "TO TRY TO FORM A GOVERNMENT, BYPASSING PM NETANYAHU. "
                "COALITION TALKS TO FOLLOW.",
        "scene": scene_israel,
    },
    {
        "num": "4", "region": "UNITED STATES", "band": OCHRE,
        "headline": "FBI PROBES HACK OF NATIONAL CRIME DATABASE",
        "body": "THE FBI IS INVESTIGATING AN APPARENT BREACH OF ITS "
                "NATIONAL CRIME INFORMATION CENTER DATABASE, USED BY "
                "POLICE ACROSS THE US.",
        "scene": scene_fbi,
    },
]


def draw_panel(cv, x, y, p):
    cv.rect(x, y, PW, 2, INK)
    cv.rect(x, y + PH - 2, PW, 2, INK)
    cv.rect(x, y, 2, PH, INK)
    cv.rect(x + PW - 2, y, 2, PH, INK)
    cv.rect(x + 2, y + 2, PW - 4, 38, p["band"])
    draw_text(cv, x + 16, y + 10, p["num"] + " - " + p["region"], 3, WHITE)
    p["scene"](cv, x + 10, y + 50, 460, 118)
    cv.hline(x + 10, x + PW - 10, y + 174, INK, 1)
    hy = y + 184
    for ln in wrap_text(p["headline"], 448, 3):
        draw_text(cv, x + 16, hy, ln, 3, INK)
        hy += 23
    by = hy + 8
    for ln in wrap_text(p["body"], 448, 2):
        draw_text(cv, x + 16, by, ln, 2, INK)
        by += 17


def draw():
    cv = Canvas(W, H, PAPER)
    # masthead
    draw_text_centered(cv, 512, 16, "THE WORLD IN ONE DAY", 2, INK, 3)
    draw_text_centered(cv, 512, 44, "FOUR FRONTS", 3, RED, 2)
    draw_text_centered(cv, 512, 76, "22 NOVEMBER 2026", 7, INK, 1)
    draw_text_centered(cv, 512, 138,
                       "SUNDAY - FOUR STORIES FROM FOUR CORNERS OF THE GLOBE",
                       2, GREY, 1)
    cv.hline(24, 1000, 164, INK, 3)
    cv.hline(24, 1000, 170, INK, 1)
    # four story panels
    positions = [(24, 196), (520, 196), (24, 542), (520, 542)]
    for pos, p in zip(positions, PANELS):
        draw_panel(cv, pos[0], pos[1], p)
    # footer: also on the day
    draw_text(cv, 24, 890, "ALSO ON THE DAY:", 2, RED)
    also = ("COP31 CLIMATE TALKS DEADLOCKED IN TURKEY | NORWAY COURT "
            "VOIDS DISPUTED OIL LICENCES | MYANMAR SHAKEN BY 4.1 QUAKE")
    ay = 912
    for ln in wrap_text(also, 976, 2):
        draw_text(cv, 24, ay, ln, 2, INK)
        ay += 18
    cv.hline(24, 1000, 956, INK, 2)
    draw_text_centered(cv, 512, 968,
                       "DRAWN FROM REPORTS OF 22 NOVEMBER 2026 - "
                       "BBC - REUTERS - AP - CNN", 2, GREY, 1)
    return cv


def main():
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    data = png_bytes(draw())
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as f:
        f.write(data)
    print("wrote %s (%d bytes)" % (path, len(data)))


if __name__ == "__main__":
    main()
