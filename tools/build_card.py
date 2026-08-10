"""Generate dark_mode.svg / light_mode.svg for ayushmaninbox's profile README.

Run once to lay out the card. today.py then patches only the id-tagged values daily.

The left panel is the portrait, embedded as a base64 JPEG and blended into the card
background; the right panel is the neofetch-style info block.
"""
import datetime
from xml.sax.saxutils import escape
import base64
import io
from PIL import Image
import numpy as np
from dateutil import relativedelta

SRC = 'components/portrait-source.png'   # gitignored; local only

# The source is RGBA and never fully opaque (peak alpha 215, 68% of pixels partial).
# It is embedded as a lossless PNG with that alpha intact and NO background behind it,
# so the card colour shows through the soft edge instead of a flattened black box.
# The only per-file operation is inverting RGB; alpha is carried through untouched.
IMG_X, IMG_Y, IMG_H = 15, 28, 474    # width is derived from the source aspect (never crops)
IMG_SCALE = 2                        # 2x for retina; 3x tripled the bytes for no visible gain
IMG_GAP = 22                         # gutter between portrait and info column
GREY_TOL = 8                         # max RGB spread before we stop treating it as greyscale

INFO_W, INFO_FS, LH = 64, 16, 20     # info column: chars per line, font size, line height
# The stat rows can't always justify down to INFO_W: once a value hits 9 digits the dot
# leaders are already empty, so the line grows instead. Real numbers put the LOC row at
# 66, hence the slack -- 3 chars keeps it inside the card as those figures climb.
INFO_SLACK = 3
ADV = 0.5995                         # ConsolasFallback advance, in em
H = 530

# the glow/shadow reads naturally over a dark card, so the untouched image goes there;
# light mode gets the inversion
THEMES = {
    'dark_mode.svg':  dict(invert=False, bg='#161b22', fg='#c9d1d9', key='#ffa657',
                           val='#a5d6ff', add='#3fb950', dele='#f85149', cc='#616e7f'),
    'light_mode.svg': dict(invert=True,  bg='#f6f8fa', fg='#24292f', key='#953800',
                           val='#0a3069', add='#1a7f37', dele='#cf222e', cc='#c2cfde'),
}


# ---------------------------------------------------------------- portrait panel
def panel_width():
    """Panel width that matches the source aspect exactly, so nothing is ever cropped."""
    w, h = Image.open(SRC).size
    return int(round(IMG_H * w / h))


def portrait_data_uri(theme):
    """Scale the portrait and, for one file, invert the colour. Alpha always survives.

    Encoded lossless -- JPEG has no alpha channel, so it has to be flattened onto some
    colour first, and that flattening is what smeared the soft edge before.

    This source is neutral (mean RGB spread 1.2/255), so it is stored as luminance +
    alpha rather than RGBA: same pixels to the eye, half the bytes. A genuinely
    coloured source falls back to RGBA automatically.
    """
    im = Image.open(SRC).convert('RGBA').resize(
        (panel_width() * IMG_SCALE, IMG_H * IMG_SCALE), Image.LANCZOS)
    a = np.asarray(im).astype(np.int16)
    greyscale = int((a[..., :3].max(2) - a[..., :3].min(2)).mean()) <= GREY_TOL

    if greyscale:
        lum = a[..., :3].mean(2)
        if theme['invert']:
            lum = 255 - lum
        out = np.dstack([lum, a[..., 3]]).clip(0, 255).astype(np.uint8)
        img = Image.fromarray(out).convert('LA')
    else:
        if theme['invert']:
            a[..., :3] = 255 - a[..., :3]    # alpha channel deliberately untouched
        img = Image.fromarray(a.clip(0, 255).astype(np.uint8)).convert('RGBA')

    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    raw = buf.getvalue()
    return 'data:image/png;base64,' + base64.b64encode(raw).decode('ascii'), len(raw)


# ---------------------------------------------------------------- info rows
def uptime(birth=datetime.date(2005, 9, 8), today=None):
    today = today or datetime.date.today()
    d = relativedelta.relativedelta(today, birth)
    p = lambda n, u: f"{n} {u}{'s' if n != 1 else ''}"
    return f"{p(d.years,'year')}, {p(d.months,'month')}, {p(d.days,'day')}"


ROWS_DATA = [
    ('OS',                    'Mac M4, Arch Linux, Windows 11, Android 16', None),
    ('Uptime',                uptime(),                                     'age_data'),
    ('Host',                  'VIT University, Vellore',                    None),
    ('Kernel',                'Full Stack Software Developer',              None),
    ('IDE',                   'VS Code, Xcode',                             None),
    (None, None, None),
    ('Languages.Programming', 'Python, Java, JavaScript, C, C++, R',        None),
    ('Languages.Computer',    'HTML, CSS, TypeScript, JSON, YAML',          None),
    ('Languages.Real',        'English, Hindi',                       None),
    (None, None, None),
    ('Hobbies.Software',      'Logic Pro, FL Studio, one genre per week',   None),
    ('Hobbies.Hardware',      'Bricking, and then unbricking my pc',        None),
]
CONTACT = [
    ('Email',     'ayushmanmohapatra895@gmail.com'),
    ('LinkedIn',  'ayushman-mohapatra'),
    ('Instagram', 'ayushmaninbox'),
    ('Portfolio', 'ayushmaninbox.in'),
]


def kv(x, y, key, value, vid=None):
    """`. Key: ....... value`, padded so the whole line is INFO_W chars."""
    keytxt = '.'.join(f'<tspan class="key">{escape(p)}</tspan>' for p in key.split('.'))
    dots = max(3, INFO_W - len(f'. {key}:{value}') - 2)
    idattr = f' id="{vid}"' if vid else ''
    dotid = f' id="{vid}_dots"' if vid else ''
    return (f'<tspan x="{x}" y="{y}" class="cc">. </tspan>{keytxt}:'
            f'<tspan class="cc"{dotid}> {"." * dots} </tspan>'
            f'<tspan class="value"{idattr}>{escape(value)}</tspan>')


def rule(x, y, label):
    return f'<tspan x="{x}" y="{y}">{escape(label)}</tspan> -{"—" * (INFO_W - len(label) - 5)}-—-'


def blank(x, y):
    return f'<tspan x="{x}" y="{y}" class="cc">. </tspan>'


def build(theme_file):
    t = THEMES[theme_file]
    uri, nbytes = portrait_data_uri(t)
    iw = panel_width()
    info_x = IMG_X + iw + IMG_GAP
    W = int(round(info_x + (INFO_W + INFO_SLACK) * INFO_FS * ADV)) + 15
    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" '
        f'width="{W}px" height="{H}px" font-size="{INFO_FS}px">',
        '<style>',
        '@font-face {',
        "src: local('Consolas'), local('Consolas Bold');",
        "font-family: 'ConsolasFallback';",
        'font-display: swap;',
        '-webkit-size-adjust: 109%;',
        'size-adjust: 109%;',
        '}',
        f'.key {{fill: {t["key"]};}}',
        f'.value {{fill: {t["val"]};}}',
        f'.addColor {{fill: {t["add"]};}}',
        f'.delColor {{fill: {t["dele"]};}}',
        f'.cc {{fill: {t["cc"]};}}',
        'text, tspan {white-space: pre;}',
        '</style>',
        f'<rect width="{W}px" height="{H}px" fill="{t["bg"]}" rx="15"/>',
        f'<image x="{IMG_X}" y="{IMG_Y}" width="{iw}" height="{IMG_H}" href="{uri}"/>',
    ]

    out.append(f'<text x="{info_x}" y="30" fill="{t["fg"]}">')
    y = 30
    handle = '@ayushmaninbox'
    out.append(f'<tspan x="{info_x}" y="{y}">{handle}</tspan> -{"—" * (INFO_W - len(handle) - 5)}-—-')
    for key, val, vid in ROWS_DATA:
        y += LH
        out.append(kv(info_x, y, key, val, vid) if key else blank(info_x, y))
    y += LH; out.append(blank(info_x, y))
    y += LH; out.append(rule(info_x, y, '- Contact'))
    for key, val in CONTACT:
        y += LH
        out.append(kv(info_x, y, key, val))
    y += LH; out.append(blank(info_x, y))
    y += LH; out.append(rule(info_x, y, '- GitHub Stats'))

    # dynamic stat rows -- today.py rewrites the value + _dots pairs
    y += LH
    out.append(
        f'{blank(info_x, y)}<tspan class="key">Repos</tspan>:'
        f'<tspan class="cc" id="repo_data_dots"> ......... </tspan><tspan class="value" id="repo_data">0</tspan>'
        f' {{<tspan class="key">Contributed</tspan>: <tspan class="value" id="contrib_data">0</tspan>}}'
        f' | <tspan class="key">Stars</tspan>:<tspan class="cc" id="star_data_dots"> ............. </tspan>'
        f'<tspan class="value" id="star_data">0</tspan>')
    y += LH
    out.append(
        f'{blank(info_x, y)}<tspan class="key">Commits</tspan>:'
        f'<tspan class="cc" id="commit_data_dots"> ........................ </tspan>'
        f'<tspan class="value" id="commit_data">0</tspan>'
        f' | <tspan class="key">Followers</tspan>:<tspan class="cc" id="follower_data_dots"> ........... </tspan>'
        f'<tspan class="value" id="follower_data">0</tspan>')
    y += LH
    out.append(
        f'{blank(info_x, y)}<tspan class="key">Lines of Code on GitHub</tspan>:'
        f'<tspan class="cc" id="loc_data_dots">. </tspan><tspan class="value" id="loc_data">0</tspan>'
        f' ( <tspan class="addColor" id="loc_add">0</tspan><tspan class="addColor">++</tspan>, '
        f'<tspan id="loc_del_dots"> </tspan><tspan class="delColor" id="loc_del">0</tspan>'
        f'<tspan class="delColor">--</tspan> )')
    out += ['</text>', '</svg>']
    return '\n'.join(out) + '\n'


if __name__ == '__main__':
    import sys
    dest = sys.argv[1] if len(sys.argv) > 1 else '.'
    for name in THEMES:
        svg = build(name)
        open(f'{dest}/{name}', 'w').write(svg)
        _, nbytes = portrait_data_uri(THEMES[name])
        inv = 'RGB inverted' if THEMES[name]['invert'] else 'untouched   '
        print(f'wrote {dest}/{name:16s} {inv}  png {nbytes/1024:4.0f} KB  svg {len(svg)/1024:4.0f} KB')
    iw = panel_width()
    info_x = IMG_X + iw + IMG_GAP
    print(f'panel: {iw}x{IMG_H} (source aspect, no crop), encoded at {IMG_SCALE}x')
    print(f'info : x={info_x}, {INFO_W}(+{INFO_SLACK}) chars -> card {int(round(info_x + (INFO_W+INFO_SLACK)*INFO_FS*ADV))+15}x{H}')
    print('uptime today:', uptime())
