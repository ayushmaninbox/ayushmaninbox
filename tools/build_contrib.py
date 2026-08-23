"""Isometric contribution chart + streak widget, appended below the main card.

Mirrors GitHub's own "3D" contribution view: a full-width isometric calendar with two
bordered stat cards overlaid in its empty corners -- Contributions top-right, Streaks
bottom-left -- since the ribbon runs from short bars at the top-left down to tall ones
at the bottom-right, leaving those two corners empty.

build_card.py reserves the canvas space for this widget using the same sizing formulas
as here, assuming a 53-week calendar -- the worst case, so a real 52-week calendar never
overflows it. today.py calls render_widget() each run to fill that reserved space with
the current data.
"""
from xml.sax.saxutils import escape

MARGIN = 15                 # matches build_card.py's IMG_X, so both sections line up
INSET = 20                  # padding between the widget's edge and its content
ASPECT = 9 / 16              # widget is a full 16:9 panel, not a tight fit around the chart
N_ASSUMED_WEEKS = 53        # GitHub's calendar is never wider than this
TILE_RATIO = 0.46           # tile_h / tile_w -- steep enough that bars read as tall, not squat
MAX_H_RATIO = 2.6           # tallest bar's height, as a multiple of tile_w
FONT = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

# Card sizing: computed from content, not fixed -- see stat_card().
BOX_PAD = 18
COL_GAP = 125
COL_CONTENT_W = 90
BOX_ROW_H = 94

# Empty days sit close to the background, and color runs smoothly from low to high
# with contribution count -- the same ratio height uses, so two bars of similar
# height always land on similar color, not just similar count. low/high are GitHub's
# own level-1/level-4 greens, so the gradient stays a true green, not lime.
WIDGET_THEMES = {
    'dark_mode.svg': dict(
        fg='#c9d1d9', label='#8b949e', accent='#39d353', border='#30363d', bg='#161b22',
        empty='#242920', low='#0e4429', high='#39d353'),
    'light_mode.svg': dict(
        fg='#24292f', label='#57606a', accent='#216e39', border='#d0d7de', bg='#f6f8fa',
        empty='#efece0', low='#9be9a8', high='#216e39'),
}


def lerp_color(c1, c2, t):
    c1, c2 = c1.lstrip('#'), c2.lstrip('#')
    r1, g1, b1 = int(c1[0:2], 16), int(c1[2:4], 16), int(c1[4:6], 16)
    r2, g2, b2 = int(c2[0:2], 16), int(c2[2:4], 16), int(c2[4:6], 16)
    r, g, b = (round(a + (b - a) * t) for a, b in ((r1, r2), (g1, g2), (b1, b2)))
    return f'#{r:02x}{g:02x}{b:02x}'


def panel_width(card_width):
    return card_width - 2 * MARGIN


def tile_size(card_width):
    """Tile footprint sized so the chart fills the widget width, assuming a 53-week
    calendar. A real (<=53 week) calendar comes out narrower, never wider."""
    chart_w_target = panel_width(card_width) - 2 * INSET
    tile_w = chart_w_target / ((N_ASSUMED_WEEKS + 7) / 2)
    return tile_w, tile_w * TILE_RATIO


def panel_height(card_width):
    """A full 16:9 panel -- generously sized, not a tight fit around the chart -- so
    the widget reads as a spacious section rather than a cramped strip. Never smaller
    than the chart's worst case (53 weeks, tallest bar at the top-left corner), so a
    narrow card whose 16:9 height would be too tight still never clips the chart."""
    tile_w, tile_h = tile_size(card_width)
    max_h = tile_w * MAX_H_RATIO
    footprint_h = tile_h * (N_ASSUMED_WEEKS + 5) / 2 + tile_h
    chart_required = footprint_h + max_h + 2 * INSET
    return max(chart_required, panel_width(card_width) * ASPECT)


def shade(hex_color, factor):
    hex_color = hex_color.lstrip('#')
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    r, g, b = (max(0, min(255, int(c * factor))) for c in (r, g, b))
    return f'#{r:02x}{g:02x}{b:02x}'


def render_chart(weeks, theme, tile_w, tile_h):
    """Renders the calendar as an isometric grid of extruded tiles, one per day.

    Height and color are driven by the exact same ratio (count / busiest day), so two
    bars of similar height always land on similar color instead of jumping between a
    handful of banded shades. Tiles are painted back-to-front (by col+row) so nearer
    bars correctly occlude the ones behind them.
    """
    min_h, max_h = max(2.0, tile_w * 0.1), tile_w * MAX_H_RATIO
    all_days = [d for w in weeks for d in w['contributionDays']]
    max_count = max((d['contributionCount'] for d in all_days), default=1) or 1

    def bar_height(c):
        return min_h if c == 0 else min_h + (max_h - min_h) * (c / max_count)

    def color_for(c):
        return theme['empty'] if c == 0 else lerp_color(theme['low'], theme['high'], c / max_count)

    def iso_n(col, row):
        return (col - row) * (tile_w / 2), (col + row) * (tile_h / 2)

    tiles = [(col, d['weekday'], d) for col, week in enumerate(weeks) for d in week['contributionDays']]
    tiles.sort(key=lambda t: t[0] + t[1])  # back-to-front paint order

    parts = []
    minx = miny = float('inf')
    maxx = maxy = float('-inf')
    for col, row, d in tiles:
        nx, ny = iso_n(col, row)
        h = bar_height(d['contributionCount'])
        color = color_for(d['contributionCount'])
        ty = ny - h
        N, E, S, W = (nx, ty - tile_h / 2), (nx + tile_w / 2, ty), (nx, ty + tile_h / 2), (nx - tile_w / 2, ty)
        Sg, Eg, Wg = (nx, ny + tile_h / 2), (nx + tile_w / 2, ny), (nx - tile_w / 2, ny)

        def pts(*p):
            return ' '.join(f'{x:.1f},{y:.1f}' for x, y in p)
        if h > min_h + 0.5:
            left_c, right_c = shade(color, 0.8), shade(color, 0.62)
            parts.append(f'<polygon points="{pts(W,S,Sg,Wg)}" fill="{left_c}" stroke="{left_c}" stroke-width="0.5"/>')
            parts.append(f'<polygon points="{pts(E,S,Sg,Eg)}" fill="{right_c}" stroke="{right_c}" stroke-width="0.5"/>')
        parts.append(f'<polygon points="{pts(N,E,S,W)}" fill="{color}" stroke="{color}" stroke-width="0.5"/>')
        for px, py in (N, E, S, W, Sg, Eg, Wg):
            minx, maxx = min(minx, px), max(maxx, px)
            miny, maxy = min(miny, py), max(maxy, py)

    frag = f'<g transform="translate({-minx:.1f},{-miny:.1f})">' + ''.join(parts) + '</g>'
    return frag, maxx - minx, maxy - miny


def compute_stats(days):
    """Total, best day, and longest/current streaks from a chronological list of days.

    The current streak treats today specially: if today has 0 contributions the day
    isn't over yet, so it's skipped rather than treated as a break -- the streak is
    evaluated as of yesterday instead. Without that, the streak reads as broken for
    the entire day even though there's still time left to contribute.
    """
    total = sum(d['contributionCount'] for d in days)
    best = max(days, key=lambda d: d['contributionCount'])

    longest_len, longest_start, longest_end = 0, None, None
    run_start, run = None, 0
    for d in days:
        if d['contributionCount'] > 0:
            if run == 0:
                run_start = d['date']
            run += 1
            if run > longest_len:
                longest_len, longest_start, longest_end = run, run_start, d['date']
        else:
            run = 0

    idx = len(days) - 1
    if days[idx]['contributionCount'] == 0:
        idx -= 1
    current_len, current_start, current_end = 0, None, days[idx]['date'] if idx >= 0 else None
    while idx >= 0 and days[idx]['contributionCount'] > 0:
        current_start = days[idx]['date']
        current_len += 1
        idx -= 1

    return dict(total=total, best_count=best['contributionCount'], best_date=best['date'],
                longest_len=longest_len, longest_start=longest_start, longest_end=longest_end,
                current_len=current_len, current_start=current_start, current_end=current_end,
                range_start=days[0]['date'], range_end=days[-1]['date'])


def month_day(iso_date):
    import datetime
    return datetime.date.fromisoformat(iso_date).strftime('%b %-d')


def stat_cell(x, y, value, label, sub, theme):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="24" font-weight="700" fill="{theme["accent"]}">{escape(value)}</text>'
            f'<text x="{x:.1f}" y="{y+18:.1f}" font-size="12" font-weight="600" fill="{theme["fg"]}">{escape(label)}</text>'
            f'<text x="{x:.1f}" y="{y+32:.1f}" font-size="10" fill="{theme["label"]}">{escape(sub)}</text>')


def stat_card(x, y, title, cells, theme):
    """A bordered rounded-rect card, sized snugly around its content: a title above,
    evenly spaced stat cells inside. Returns (markup, width, height)."""
    w = 2 * BOX_PAD + (len(cells) - 1) * COL_GAP + COL_CONTENT_W
    h = BOX_ROW_H
    parts = [f'<text x="{x:.1f}" y="{y-9:.1f}" font-size="13" font-weight="700" fill="{theme["fg"]}">{escape(title)}</text>',
             f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="8" fill="none" stroke="{theme["border"]}"/>']
    for i, (value, label, sub) in enumerate(cells):
        cx = x + BOX_PAD + COL_GAP * i
        parts.append(stat_cell(cx, y + 39, value, label, sub, theme))
    return ''.join(parts), w, h


def render_widget(theme, card_width, weeks):
    """Returns the SVG markup for the whole widget, in local coordinates starting at (0,0)."""
    avail_w = panel_width(card_width)
    panel_h = panel_height(card_width)
    tile_w, tile_h = tile_size(card_width)
    chart_frag, cw, ch = render_chart(weeks, theme, tile_w, tile_h)

    days = [d for w in weeks for d in w['contributionDays']]
    stats = compute_stats(days)
    this_week = weeks[-1]['contributionDays']
    this_week_total = sum(d['contributionCount'] for d in this_week)
    avg_per_day = stats['total'] / len(days)

    parts = [f'<g font-family="{FONT}">']

    chart_y = INSET + max(0, ((panel_h - 2 * INSET) - ch) / 2)
    parts.append(f'<g transform="translate({INSET},{chart_y:.1f})">{chart_frag}</g>')

    contrib_y = INSET + 22
    contrib_markup, contrib_w, contrib_h = stat_card(0, contrib_y, 'Contributions', [
        (f'{stats["total"]:,}', 'Total', f'{month_day(stats["range_start"])} → {month_day(stats["range_end"])}'),
        (f'{this_week_total:,}', 'This week', f'{month_day(this_week[0]["date"])} → {month_day(this_week[-1]["date"])}'),
        (f'{stats["best_count"]:,}', 'Best day', month_day(stats['best_date'])),
    ], theme)
    contrib_x = avail_w - INSET - contrib_w
    parts.append(f'<g transform="translate({contrib_x:.1f},0)">{contrib_markup}</g>')
    avg_y = contrib_y + contrib_h + 15
    parts.append(f'<text x="{avail_w-INSET:.1f}" y="{avg_y:.1f}" font-size="11" fill="{theme["fg"]}" text-anchor="end">'
                 f'Average: <tspan font-weight="700" fill="{theme["accent"]}">{avg_per_day:.2f}</tspan> / day</text>')

    streak_markup, streak_w, streak_h = stat_card(INSET, 0, 'Streaks', [
        (f'{stats["longest_len"]} days', 'Longest',
         f'{month_day(stats["longest_start"])} → {month_day(stats["longest_end"])}' if stats['longest_start'] else '—'),
        (f'{stats["current_len"]} days', 'Current',
         f'{month_day(stats["current_start"])} → {month_day(stats["current_end"])}' if stats['current_start'] else '—'),
    ], theme)
    streak_y = panel_h - INSET - streak_h
    parts.append(f'<g transform="translate(0,{streak_y:.1f})">{streak_markup}</g>')

    parts.append('</g>')
    return ''.join(parts)
