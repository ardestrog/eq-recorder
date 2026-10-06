#!/usr/bin/env python3
# The shebang is deliberately generic: update_icon.sh always runs this script
# with the venv interpreter explicitly ("$PROJECT_DIR/.venv/bin/python3.10").
"""Apply a macOS-style rounded-square ("squircle") mask to a square PNG.

Called by update_icon.sh for any source logo, so the Dock/Finder icon gets
the same rounded corners as neighbouring apps instead of a bare square
(which is what a logo without its own transparent corners would otherwise
be).

The corner radius is 224/1024 = 21.875% of the side. It is a visual match to
system icons, not an official Apple constant: the real Big Sur+ shape is a
superellipse rather than a circular arc, and the arc is a deliberate
simplification whose difference is not visible.

The mask is rendered at 4x and downsampled (LANCZOS) so its edge is smooth
on Retina displays.
"""
import sys

from PIL import Image, ImageDraw

CORNER_RATIO = 224 / 1024
SUPERSAMPLE = 4


def apply_squircle_mask(src_path: str, dst_path: str) -> None:
    im = Image.open(src_path).convert("RGBA")
    size = im.size[0]          # the caller guarantees a square (checked in the .sh)
    radius = int(size * CORNER_RATIO)

    hi = size * SUPERSAMPLE
    mask_hi = Image.new("L", (hi, hi), 0)
    ImageDraw.Draw(mask_hi).rounded_rectangle(
        [0, 0, hi - 1, hi - 1], radius=radius * SUPERSAMPLE, fill=255)
    mask = mask_hi.resize((size, size), Image.LANCZOS)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    out.save(dst_path)


if __name__ == "__main__":
    apply_squircle_mask(sys.argv[1], sys.argv[2])
