"""Generate printable PDF attendee badges for PyBeach."""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd
from reportlab.graphics import renderPDF
from reportlab.lib.colors import HexColor
from reportlab.lib.colors import black
from reportlab.lib.colors import white
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from svglib.svglib import svg2rlg


# ---------------- HELPER FUNCTIONS ----------------
def return_fontsize_that_fits(
    badge_width: float,
    text: str,
    font_size: int,
    font_name: str = "Helvetica",
    min_size: int = 8,
) -> int:
    """Determine a fontsize for a line of text so that it fits on one line.

    Args:
        badge_width: Available width in reportlab points.
        text: Text string to measure.
        font_size: Initial font size to try.
        font_name: Font name used for width measurement.
        min_size: Minimum font size threshold.

    Returns:
        Font size that fits within badge_width.
    """
    if not text:
        return font_size
    text_width = stringWidth(text, font_name, font_size)
    while text_width > badge_width and font_size > min_size:
        font_size -= 1
        text_width = stringWidth(text, font_name, font_size)
    return font_size


def format_pronouns(pronoun_str: str) -> str:
    """Format pronouns with capitalized words separated by ' / '.

    Args:
        pronoun_str: Raw pronoun string from attendee input.

    Returns:
        Formatted pronoun string.
    """
    cleaned = " ".join(pronoun_str.split())
    cleaned = re.sub(r"\s*/\s*", " / ", cleaned)
    return " ".join(word.capitalize() for word in cleaned.split())


def resolve_asset_path(file_path: str | Path | None) -> Path | None:
    """Resolve an asset path, checking both cwd and script directory.

    Args:
        file_path: Path string or Path object, or None.

    Returns:
        Resolved Path object, or None if file_path was None or empty.
    """
    if not file_path:
        return None
    path_obj = Path(file_path)
    if path_obj.exists():
        return path_obj
    script_relative = Path(__file__).parent / file_path
    if script_relative.exists():
        return script_relative
    return path_obj


def load_scaled_svg(svg_path: str | Path, target_size: float):
    """Load an SVG file and pre-scale it to fit within target_size box.

    Args:
        svg_path: Path to SVG file on disk.
        target_size: Maximum width/height dimension in points.

    Returns:
        Scaled ReportLab Drawing, or None if file cannot be loaded.
    """
    path_obj = resolve_asset_path(svg_path)
    if not path_obj or not path_obj.exists():
        return None
    try:
        drawing = svg2rlg(str(path_obj))
        if drawing is None or drawing.width == 0 or drawing.height == 0:
            return None
        scale = min(target_size / drawing.width, target_size / drawing.height)
        drawing.width *= scale
        drawing.height *= scale
        drawing.scale(scale, scale)
        return drawing
    except Exception as exc:
        print(f"Warning: Failed to load SVG '{svg_path}': {exc}", file=sys.stderr)
        return None


def load_background_svg(svg_path: str | Path, width: float, height: float):
    """Load an SVG background and scale it to badge dimensions.

    Args:
        svg_path: Path to SVG file on disk.
        width: Target width in points.
        height: Target height in points.

    Returns:
        Scaled ReportLab Drawing, or None if file cannot be loaded.
    """
    path_obj = resolve_asset_path(svg_path)
    if not path_obj or not path_obj.exists():
        return None
    try:
        drawing = svg2rlg(str(path_obj))
        if drawing is None or drawing.width == 0 or drawing.height == 0:
            return None
        scale_x = width / drawing.width
        scale_y = height / drawing.height
        drawing.width = width
        drawing.height = height
        drawing.scale(scale_x, scale_y)
        return drawing
    except Exception as exc:
        print(
            f"Warning: Failed to load background SVG '{svg_path}': {exc}",
            file=sys.stderr,
        )
        return None


def validate_opacity(val: str) -> float:
    """Validate opacity CLI argument is a float between 0.0 and 1.0.

    Args:
        val: Input string value from CLI.

    Returns:
        Float opacity value.

    Raises:
        argparse.ArgumentTypeError: If value is not a float or outside [0.0, 1.0].
    """
    try:
        opacity = float(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid float value: '{val}'.")
    if not (0.0 <= opacity <= 1.0):
        raise argparse.ArgumentTypeError(
            f"Opacity must be between 0.0 and 1.0; got {val}."
        )
    return opacity


# ---------------- BADGE CREATION ----------------
def create_badges(
    csv_path: str | Path,
    output_path: str | Path = "badges.pdf",
    event_name: str = "PyBeach",
    logo_path: str | Path = "assets/pybeach2025-fullcolor.svg",
    photo_opt_out_path: str | Path = "assets/no-photos.svg",
    with_guides: bool = True,
    ribbon_color: str = "#337ab7",
    background_path: str | Path | None = "assets/pybeach2026-background.png",
    opacity: float = 0.2,
) -> int:
    """Generate attendee badges PDF from a CSV export.

    Args:
        csv_path: Path to attendee CSV file.
        output_path: Destination path for generated PDF.
        event_name: Conference banner label on badge ribbon.
        logo_path: Path to event logo SVG.
        photo_opt_out_path: Path to photo opt-out SVG icon.
        with_guides: Whether to draw dashed cut lines around badges.
        ribbon_color: Hex color string for ribbon background.
        background_path: Path to optional background image (PNG, JPG, SVG), or None for no background.
        opacity: Opacity for the background image, from 0.0 (transparent) to 1.0 (opaque).

    Returns:
        Count of badges generated.
    """
    csv_file = resolve_asset_path(csv_path)
    if not csv_file or not csv_file.exists():
        raise FileNotFoundError(f"Attendee CSV file not found: {csv_path}")

    df = pd.read_csv(csv_file)

    # Filter out donation-only rows
    if "Ticket" in df.columns:
        df_filtered = df[df["Ticket"] != "Donate to PyBeach"]
    else:
        df_filtered = df.copy()

    # Filter out rows missing photo opt-out info if present
    if "Photo opt-out" in df_filtered.columns:
        df_filtered = df_filtered[df_filtered["Photo opt-out"].notna()]

    df_filtered = df_filtered.reset_index(drop=True)

    if df_filtered.empty:
        print(f"Warning: No valid attendee rows found in {csv_path}")
        return 0

    # Badge dimensions (4" x 2 7/8")
    badge_width = 4 * 72
    badge_height = 2.875 * 72
    guide_margin = 3
    edge_margin = 8
    ribbon_height = 30
    background_bleed = 5

    # Opacity validation & background loading
    if not (0.0 <= opacity <= 1.0):
        raise ValueError(f"Opacity must be between 0.0 and 1.0; got {opacity}.")
    bg_alpha = opacity

    bg_file = resolve_asset_path(background_path) if background_path else None
    if bg_file and not bg_file.exists():
        raise FileNotFoundError(f"Background image not found: {background_path}")

    bg_drawing = None
    if bg_file and bg_file.suffix.lower() == ".svg":
        bg_drawing = load_background_svg(
            bg_file,
            badge_width + background_bleed * 2,
            badge_height + background_bleed * 2,
        )

    # 6 badges per letter page (2 columns x 3 rows)
    badge_xys = [
        (10, 565),
        (316, 565),
        (10, 338),
        (316, 338),
        (10, 111),
        (316, 111),
    ]

    # Pre-load and scale SVGs once
    logo_size = 96
    photo_opt_out_size = 50
    logo_drawing = load_scaled_svg(logo_path, logo_size)
    photo_drawing = load_scaled_svg(photo_opt_out_path, photo_opt_out_size)

    banner_color = HexColor(ribbon_color)

    c = canvas.Canvas(str(output_path), pagesize=LETTER)
    badge_count = 0
    total_badges = 0

    name_column = "What name would you like printed on your badge?"

    for index, row in df_filtered.iterrows():
        # Retrieve attendee name
        raw_name = row.get(name_column) if name_column in row else None
        if pd.isna(raw_name):
            print(f"Warning: Row {index} has missing badge name; skipping.")
            continue

        name = str(raw_name).strip()
        if name.startswith("*"):
            name = ""

        # Page break after every 6 badges
        if badge_count == 6:
            c.showPage()
            c.setFillColor(black)
            badge_count = 0

        x = badge_xys[badge_count][0]
        y = badge_xys[badge_count][1]

        # Background image (drawn behind all badge content, extending slightly beyond cut lines)
        if bg_file and bg_alpha > 0.0:
            c.saveState()
            c.setFillAlpha(bg_alpha)
            if bg_drawing:
                c.setStrokeAlpha(bg_alpha)
                renderPDF.draw(
                    bg_drawing,
                    c,
                    x - background_bleed,
                    y - background_bleed,
                )
            else:
                c.drawImage(
                    str(bg_file),
                    x - background_bleed,
                    y - background_bleed,
                    width=badge_width + background_bleed * 2,
                    height=badge_height + background_bleed * 2,
                )
            c.restoreState()

        # Photo opt-out icon (top left)
        if (
            photo_drawing
            and "Photo opt-out" in row
            and row["Photo opt-out"] == "Opt-out"
        ):
            renderPDF.draw(
                photo_drawing,
                c,
                x + edge_margin,
                y + badge_height - photo_opt_out_size - edge_margin / 2,
            )

        # Pronouns (top right)
        pronouns_option = row.get("Would you like your pronouns printed on your badge?")
        if not pd.isna(pronouns_option) and str(pronouns_option).startswith("Yes"):
            raw_pronouns = row.get("Pronouns")
            if not pd.isna(raw_pronouns) and str(raw_pronouns).strip() not in (
                "",
                "-",
            ):
                pronouns = format_pronouns(str(raw_pronouns).strip())
                c.setFont("Helvetica", 14)
                c.setFillColor(black)
                c.drawRightString(
                    x + badge_width - edge_margin,
                    y + badge_height - (edge_margin * 2),
                    pronouns,
                )

        # Event logo (top center)
        if logo_drawing:
            renderPDF.draw(
                logo_drawing,
                c,
                x + (badge_width - logo_drawing.width) / 2,
                y + badge_height - logo_drawing.height - 2,
            )

        # Affiliation / subtitle line
        typ = str(row.get("Ticket", ""))
        title = row.get("Ticket Job Title")
        company = ""

        if typ in ("Early Bird Corporate", "Corporate"):
            comp_name = row.get("Ticket Company Name")
            comp_val = (
                str(comp_name).strip()
                if not pd.isna(comp_name) and str(comp_name).strip()
                else ""
            )
            title_val = (
                str(title).strip() if not pd.isna(title) and str(title).strip() else ""
            )
            if title_val and comp_val:
                company = f"{title_val}, {comp_val}"
            else:
                company = comp_val or title_val
        elif typ in ("Early Bird Student", "Student"):
            school = row.get("What school do you attend?")
            if not pd.isna(school) and str(school).strip():
                company = f"Student, {str(school).strip()}"
            else:
                company = "Student"
        else:
            if not pd.isna(title) and str(title).strip():
                company = str(title).strip()

        # Attendee Name
        cleaned_name = re.sub(r"\s+", " ", name).strip()
        available_name_width = badge_width - (edge_margin * 2)
        font_size = return_fontsize_that_fits(
            available_name_width, cleaned_name, 20, font_name="Helvetica-Bold"
        )
        c.setFont("Helvetica-Bold", font_size)
        c.setFillColor(black)

        name_y = y + badge_height - (128 if company else 138)
        c.drawCentredString(x + badge_width / 2, name_y, cleaned_name)

        # Subtitle / Company / School line
        if company:
            available_job_width = badge_width - (edge_margin * 2)
            job_font_size = return_fontsize_that_fits(
                available_job_width, company, 16, font_name="Helvetica"
            )
            c.setFont("Helvetica", job_font_size)
            c.setFillColor(black)
            c.drawCentredString(x + badge_width / 2, y + badge_height - 150, company)

        # Order reference code (above ribbon, right-aligned)
        order_ref = row.get("Order Reference")
        if not pd.isna(order_ref) and str(order_ref).strip():
            c.setFont("Helvetica", 10)
            c.setFillColor(black)
            c.drawRightString(
                x + badge_width - edge_margin,
                y + ribbon_height + 10,
                str(order_ref).strip(),
            )

        # Bottom ribbon
        c.setFillColor(banner_color)
        c.rect(x - 5, y + 5, badge_width + 10, ribbon_height, stroke=0, fill=1)
        c.setFillColor(white)
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(x + badge_width / 2, y + (ribbon_height / 2), event_name)

        # Cutting guide lines
        if with_guides:
            c.saveState()
            c.setLineWidth(1)
            c.setDash(4, 4)
            c.setStrokeColorRGB(0.6, 0.6, 0.6)
            c.rect(
                x - guide_margin,
                y - guide_margin,
                badge_width + guide_margin * 2,
                badge_height + guide_margin * 2,
                fill=0,
            )
            c.restoreState()

        badge_count += 1
        total_badges += 1

    c.save()
    return total_badges


# ---------------- CLI PARSER ----------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate printable PDF attendee badges for PyBeach 2026.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "csv_file",
        nargs="?",
        default=None,
        help="Path to attendee CSV file (Tito export format). Defaults to sample_attendees.csv if not provided.",
    )
    parser.add_argument(
        "-i",
        "--input",
        dest="input_flag",
        default=None,
        help="Explicit flag for attendee CSV file path (overrides positional argument).",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="badges.pdf",
        help="Path for generated output PDF file.",
    )
    parser.add_argument(
        "--event-name",
        default="PyBeach - October 24, 2026",
        help="Event name / date string displayed on the bottom ribbon.",
    )
    parser.add_argument(
        "--logo",
        default="assets/pybeach2025-fullcolor.svg",
        help="Path to conference logo SVG.",
    )
    parser.add_argument(
        "--photo-opt-out-icon",
        default="assets/no-photos.svg",
        help="Path to photo opt-out SVG icon.",
    )
    parser.add_argument(
        "--guides",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Draw dashed badge cutting guides on the pages.",
    )
    parser.add_argument(
        "--ribbon-color",
        default="#337ab7",
        help="Hex color for the bottom ribbon banner.",
    )
    parser.add_argument(
        "--background-image",
        "--background",
        dest="background_image",
        default="assets/pybeach2026-background.png",
        help="Path to badge background image. Defaults to assets/pybeach2026-background.png. Set to 'none' or '' to omit.",
    )
    parser.add_argument(
        "--no-background",
        "--no-background-image",
        dest="no_background",
        action="store_true",
        default=False,
        help="Disable background image on badges.",
    )
    parser.add_argument(
        "--opacity",
        dest="opacity",
        type=validate_opacity,
        default=0.2,
        help="Background image opacity between 0.0 (transparent) and 1.0 (fully opaque).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Main execution function."""
    args = parse_args(argv)

    csv_path = args.input_flag or args.csv_file or "sample_attendees.csv"
    if args.no_background or (
        args.background_image
        and args.background_image.strip().lower() in ("none", "", "false", "no")
    ):
        background_path = None
    else:
        background_path = args.background_image

    try:
        count = create_badges(
            csv_path=csv_path,
            output_path=args.output,
            event_name=args.event_name,
            logo_path=args.logo,
            photo_opt_out_path=args.photo_opt_out_icon,
            with_guides=args.guides,
            ribbon_color=args.ribbon_color,
            background_path=background_path,
            opacity=args.opacity,
        )
        print(f"Successfully generated {count} badge(s) to '{args.output}'.")
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
