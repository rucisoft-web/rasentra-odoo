"""Pembuat diagram SVG sederhana dan konsisten untuk spesifikasi & panduan Rasentra (tanpa dependensi).

Palet mengikuti tema: oxblood (Central), saffron (Lokal/outlet), herba (perangkat & aksi berhasil),
arang (sistem luar), krem (latar).
"""

from html import escape

PALETTE = {
    "central": ("#8b2e1f", "#ffffff", "#8b2e1f"),
    "lokal": ("#fbe8d3", "#5a3410", "#d9822b"),
    "device": ("#eef3e6", "#2f4a1c", "#5b7f3a"),
    "ext": ("#2e2420", "#faf6ef", "#2e2420"),
    "plain": ("#ffffff", "#2e2420", "#cbbba8"),
    "decision": ("#fff7e8", "#5a3410", "#d9822b"),
    "warn": ("#fbe1df", "#7a1d14", "#b3261e"),
    "done": ("#e3f1e5", "#1f4d27", "#2c6e36"),
}
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


class Svg:
    def __init__(self, width, height, title):
        self.width, self.height, self.title = width, height, title
        self.parts = []

    def group(self, x, y, w, h, label, color="#cbbba8", fill="#fffdf9"):
        self.parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{fill}" stroke="{color}" '
            f'stroke-dasharray="6 5" stroke-width="1.5"/>'
            f'<text x="{x + 14}" y="{y + 22}" font-size="13" font-weight="700" fill="{color}">{escape(label)}</text>')

    def box(self, x, y, w, h, title, sub=None, kind="plain"):
        fill, text, stroke = PALETTE[kind]
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{fill}" stroke="{stroke}" '
                          f'stroke-width="1.5"/>')
        lines = title if isinstance(title, list) else [title]
        sub_lines = sub if isinstance(sub, list) else ([sub] if sub else [])
        total = len(lines) * 16 + len(sub_lines) * 14
        cy = y + h / 2 - total / 2 + 12
        for line in lines:
            self.parts.append(f'<text x="{x + w / 2}" y="{cy}" text-anchor="middle" font-size="13" font-weight="700" '
                              f'fill="{text}">{escape(line)}</text>')
            cy += 16
        for line in sub_lines:
            self.parts.append(f'<text x="{x + w / 2}" y="{cy}" text-anchor="middle" font-size="11" fill="{text}" '
                              f'opacity="0.85">{escape(line)}</text>')
            cy += 14
        return (x, y, w, h)

    def arrow(self, points, label=None, dashed=False, both=False, color="#6b5b53", label_at=0.5, label_dy=-6):
        path = " ".join(f"{'M' if i == 0 else 'L'} {px} {py}" for i, (px, py) in enumerate(points))
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        start = ' marker-start="url(#arrowStart)"' if both else ""
        self.parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6"{dash}{start} '
                          f'marker-end="url(#arrow)"/>')
        if label:
            # label pada segmen terpanjang
            seg = max(range(len(points) - 1), key=lambda i: abs(points[i + 1][0] - points[i][0])
                      + abs(points[i + 1][1] - points[i][1]))
            (x1, y1), (x2, y2) = points[seg], points[seg + 1]
            lx, ly = x1 + (x2 - x1) * label_at, y1 + (y2 - y1) * label_at
            width = 6.4 * len(label) + 10
            self.parts.append(f'<rect x="{lx - width / 2}" y="{ly + label_dy - 12}" width="{width}" height="17" rx="8" '
                              f'fill="#faf6ef" opacity="0.95"/>'
                              f'<text x="{lx}" y="{ly + label_dy}" text-anchor="middle" font-size="11" '
                              f'fill="#5c4d45">{escape(label)}</text>')

    def text(self, x, y, value, size=12, color="#5c4d45", anchor="start", weight="400"):
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" text-anchor="{anchor}" '
                          f'font-weight="{weight}">{escape(value)}</text>')

    def render(self):
        return (
            f'<svg class="diagram" viewBox="0 0 {self.width} {self.height}" role="img" aria-label="{escape(self.title)}" '
            f'xmlns="http://www.w3.org/2000/svg" font-family="{FONT}">'
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#6b5b53"/></marker>'
            '<marker id="arrowStart" viewBox="0 0 10 10" refX="1" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#6b5b53"/></marker></defs>'
            f'<title>{escape(self.title)}</title>' + "".join(self.parts) + "</svg>"
        )


def flow(title, steps, per_row=4, box_w=200, box_h=78, gap_x=46, gap_y=54):
    """Diagram alur berliku (kiri→kanan, lalu baris berikut kanan→kiri). `steps` = [(judul, layar, jenis)]."""
    rows = (len(steps) + per_row - 1) // per_row
    width = per_row * box_w + (per_row - 1) * gap_x + 40
    height = rows * box_h + (rows - 1) * gap_y + 40
    svg = Svg(width, height, title)
    positions = []
    for i, step in enumerate(steps):
        row, col = divmod(i, per_row)
        if row % 2:
            col = per_row - 1 - col
        x = 20 + col * (box_w + gap_x)
        y = 20 + row * (box_h + gap_y)
        positions.append((x, y))
        name, screen, *kind = step
        number = f"{i + 1}. "
        svg.box(x, y, box_w, box_h, _wrap(number + name, 26), _wrap(screen, 32) if screen else None,
                kind[0] if kind else "plain")
    for i in range(len(steps) - 1):
        (x1, y1), (x2, y2) = positions[i], positions[i + 1]
        if y1 == y2:
            if x2 > x1:
                svg.arrow([(x1 + box_w, y1 + box_h / 2), (x2, y2 + box_h / 2)])
            else:
                svg.arrow([(x1, y1 + box_h / 2), (x2 + box_w, y2 + box_h / 2)])
        else:
            svg.arrow([(x1 + box_w / 2, y1 + box_h), (x2 + box_w / 2, y2)])
    return svg.render()


def _wrap(text, limit):
    words, lines, line = text.split(), [], ""
    for word in words:
        if len(line) + len(word) + 1 > limit and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        lines.append(line)
    return lines[:3]
