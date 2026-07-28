"""Render the README quick-start terminal animation."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1200, 650
ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "quick-start.gif"


def first_font(*candidates):
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError(f"None of these fonts are installed: {candidates}")


MONO = first_font(
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
)
BOLD = first_font(
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)
FONT = ImageFont.truetype(MONO, 25)
SMALL = ImageFont.truetype(MONO, 20)
TITLE = ImageFont.truetype(BOLD, 34)


def draw_segments(draw, position, segments):
    x, y = position
    for text, color in segments:
        draw.text((x, y), text, font=FONT, fill=color)
        x += draw.textlength(text, font=FONT)


def draw_terminal_line(draw, position, kind, text):
    colors = {
        "prompt": "#86efac",
        "muted": "#8295ad",
        "banner_border": "#e879f9",
    }
    if kind == "banner_title":
        draw_segments(draw, position, [
            ("│  ", "#e879f9"),
            ("GitLab", "#fc6d26"),
            (" Migrator", "#67e8f9"),
            ("  v0.7.0", "#4ade80"),
            ("                                           │", "#e879f9"),
        ])
    elif kind == "banner_caps":
        draw_segments(draw, position, [
            ("│  ", "#e879f9"),
            ("Repositories", "#22d3ee"),
            ("  •  ", "#8295ad"),
            ("Metadata", "#e879f9"),
            ("  •  ", "#8295ad"),
            ("Runners", "#fde047"),
            ("  •  ", "#8295ad"),
            ("Pipelines", "#4ade80"),
            ("  •  ", "#8295ad"),
            ("Registry", "#60a5fa"),
            ("  │", "#e879f9"),
        ])
    else:
        draw.text(position, text, font=FONT, fill=colors.get(kind, "#8295ad"))


def draw_frame(lines, active=""):
    image = Image.new("RGB", (WIDTH, HEIGHT), "#101827")
    draw = ImageDraw.Draw(image)
    draw.text((60, 38), "GitLab Migrator - Quick Start", font=TITLE, fill="#f8fafc")
    draw.text(
        (60, 86),
        "Install  |  Configure  |  Verify  |  Migrate",
        font=SMALL,
        fill="#7dd3fc",
    )
    draw.rounded_rectangle((50, 125, 1150, 595), 18, fill="#0a1220")
    for x, color in ((76, "#fb7185"), (100, "#facc15"), (124, "#4ade80")):
        draw.ellipse((x, 148, x + 14, 162), fill=color)

    visible_lines = lines[-8:]
    y = 198
    for kind, text in visible_lines:
        draw_terminal_line(draw, (82, y), kind, text)
        y += 43

    if active:
        draw.text((82, y), active, font=FONT, fill="#86efac")
        cursor_x = 85 + draw.textlength(active, font=FONT)
        draw.rectangle((cursor_x, y + 3, cursor_x + 13, y + 29), fill="#f8fafc")

    draw.text(
        (600, 618),
        "Visualization only - no credentials or migration operations are used.",
        font=SMALL,
        anchor="mm",
        fill="#8295ad",
    )
    return image


def main():
    steps = [
        (
            "$ pipx install git+https://github.com/andjoy404/gitlab-migrator.git",
            "Installed gitlab-migrator",
        ),
        ("$ cp .env.example .env", None),
        ("$ $EDITOR .env", "# Add source and destination settings"),
        (
            "$ gitlab-migrator --version",
            [
                ("banner_border", "╭────────────────────────────────────────────────────────────────────╮"),
                ("banner_title", ""),
                ("banner_caps", ""),
                ("banner_border", "╰────────────────────────────────────────────────────────────────────╯"),
                ("muted", "gitlab-migrator 0.7.0"),
            ],
        ),
        ("$ gitlab-migrator migrate all", "Continue migration? (yes/no):"),
    ]
    frames, durations, lines = [], [], []

    for command, response in steps:
        for length in range(1, len(command) + 1, 4):
            frames.append(draw_frame(lines, command[:length]))
            durations.append(55)
        frames.append(draw_frame(lines, command))
        durations.append(700)
        lines.append(("prompt", command))
        if response:
            if isinstance(response, list):
                lines.extend(response)
            else:
                lines.append(("muted", response))
            frames.append(draw_frame(lines))
            durations.append(900)

    frames.append(draw_frame(lines))
    durations.append(2500)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
