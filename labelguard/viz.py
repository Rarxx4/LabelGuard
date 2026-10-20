"""Draws finding locations on the artwork."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from .schemas import Finding, PageImage, Verdict

COLORS = {
    Verdict.FAIL: (214, 40, 40),
    Verdict.NEEDS_REVIEW: (230, 150, 0),
    Verdict.PASS: (34, 150, 80),
    Verdict.NOT_APPLICABLE: (130, 130, 130),
}


def _font(size):
    for name in ("arialbd.ttf", "DejaVuSans-Bold.ttf", "Arial Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)  # Linux servers without fonts (Pillow >= 10.1)


def annotate(page: PageImage, findings: list[Finding], highlight: str | None = None,
             show_pass: bool = False) -> Image.Image:
    """Boxes for every located piece of artwork evidence on this page.

    highlight: finding_id to emphasise (others are drawn faintly).
    """
    img = Image.open(page.png_path).convert("RGB")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    W, H = img.size
    font = _font(max(14, W // 90))
    labels_at: dict[tuple, int] = {}  # boxes already labelled at this position -> shift the next label
    for f in findings:
        if f.verdict == Verdict.PASS and not show_pass and f.finding_id != highlight:
            continue
        if f.verdict == Verdict.NOT_APPLICABLE or f.review_decision == "dismissed":
            continue
        color = COLORS[f.verdict]
        focus = highlight is None or f.finding_id == highlight
        for ev in f.evidence:
            if ev.source != "artwork" or ev.bbox is None or ev.page != page.index:
                continue
            x0, y0, x1, y1 = ev.bbox
            pad = 0.004
            box = [(x0 - pad) * W, (y0 - pad) * H, (x1 + pad) * W, (y1 + pad) * H]
            alpha = 255 if focus else 70
            width = 5 if f.finding_id == highlight else 3
            if focus:
                draw.rectangle(box, fill=color + (40,))
                # White halo keeps the box visible on backgrounds of the same colour.
                draw.rectangle([box[0] - width, box[1] - width, box[2] + width, box[3] + width],
                               outline=(255, 255, 255, 230), width=width)
            draw.rectangle(box, outline=color + (alpha,), width=width)
            if focus:
                label = f.finding_id
                tw = draw.textlength(label, font=font) + 10
                key = (round(box[0]), round(box[1]))
                lx = box[0] + labels_at.get(key, 0)
                labels_at[key] = labels_at.get(key, 0) + tw + 4
                draw.rectangle([lx, box[1] - font.size - 8, lx + tw, box[1]], fill=color + (255,))
                draw.text((lx + 5, box[1] - font.size - 5), label, fill=(255, 255, 255, 255), font=font)
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
