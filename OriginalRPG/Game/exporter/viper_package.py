#!/usr/bin/env python3
"""Packs a web export (an HTML page and the files beside it) into a desktop app.

  windows: one .exe with the game's icon, built from desktop/bin/viper-launcher-windows.exe
  linux:   one executable, built from desktop/bin/viper-launcher-linux

The launcher serves the packed files on 127.0.0.1 and shows them in a window
(see desktop/launcher.cpp). Python 3.10+, standard library only.
"""
import argparse
import html as html_lib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = Path(__file__).resolve().parent
LAUNCHERS = {'windows': HERE / 'desktop' / 'bin' / 'viper-launcher-windows.exe',
             'linux': HERE / 'desktop' / 'bin' / 'viper-launcher-linux'}
SKIP_DIRS = {'.git', '.svn', '__pycache__', 'node_modules'}
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


class PackageError(ValueError):
    pass


# ------------------------------------------------------------------ images

def png_decode(data):
    """Returns (width, height, rgba bytes) for a non-interlaced 8/16-bit PNG."""
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise PackageError('Icon is not a PNG file')
    pos, idat, palette, alpha = 8, [], None, None
    width = height = depth = ctype = interlace = None
    while pos + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b'IHDR':
            width, height, depth, ctype, _, _, interlace = struct.unpack('>IIBBBBB', chunk)
        elif kind == b'PLTE':
            palette = [chunk[i:i + 3] for i in range(0, len(chunk) - 2, 3)]
        elif kind == b'tRNS':
            alpha = chunk
        elif kind == b'IDAT':
            idat.append(chunk)
        elif kind == b'IEND':
            break
    if width is None or not idat:
        raise PackageError('Icon PNG is damaged')
    if interlace:
        raise PackageError('Icon PNG is interlaced; save it without interlacing')
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(ctype)
    if channels is None or depth not in ((1, 2, 4, 8) if ctype in (0, 3) else (8, 16)):
        raise PackageError(f'Unsupported icon PNG format (colour type {ctype}, {depth}-bit)')
    raw = zlib.decompress(b''.join(idat))
    bits = channels * depth
    stride = (width * bits + 7) // 8
    bpp = max(1, bits // 8)
    rows, prev, at = [], bytearray(stride), 0
    for _ in range(height):
        kind, line = raw[at], bytearray(raw[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if kind == 1:
                line[i] = (line[i] + a) & 255
            elif kind == 2:
                line[i] = (line[i] + b) & 255
            elif kind == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif kind == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(bytes(line))
        prev = line
    out = bytearray()
    for line in rows:
        if depth < 8:
            per = 8 // depth
            samples = [(line[x // per] >> (8 - depth * (x % per + 1))) & ((1 << depth) - 1) for x in range(width)]
        elif depth == 16:
            samples = line[0::2]
        else:
            samples = line
        if ctype == 3:
            for index in samples[:width]:
                rgb = palette[index] if palette and index < len(palette) else b'\0\0\0'
                out += rgb + bytes([alpha[index] if alpha and index < len(alpha) else 255])
        elif ctype == 0:
            scale = 255 // ((1 << depth) - 1) if depth < 8 else 1
            for v in samples[:width]:
                out += bytes([v * scale] * 3 + [255])
        elif ctype == 4:
            for x in range(width):
                v = samples[2 * x]
                out += bytes([v, v, v, samples[2 * x + 1]])
        elif ctype == 2:
            for x in range(width):
                out += bytes(samples[3 * x:3 * x + 3]) + b'\xff'
        else:
            out += bytes(samples[:4 * width])
    return width, height, bytes(out)


def png_encode(width, height, rgba):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))
    stride = width * 4
    raw = b''.join(b'\0' + rgba[y * stride:(y + 1) * stride] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def square(width, height, rgba):
    """Centres the image on a transparent square canvas."""
    if width == height:
        return width, rgba
    size = max(width, height)
    ox, oy = (size - width) // 2, (size - height) // 2
    out = bytearray(size * size * 4)
    for y in range(height):
        start = ((y + oy) * size + ox) * 4
        out[start:start + width * 4] = rgba[y * width * 4:(y + 1) * width * 4]
    return size, bytes(out)


def resize(size, rgba, target):
    """Box filter when shrinking; nearest neighbour when growing (keeps pixel art crisp)."""
    if size == target:
        return rgba
    out = bytearray(target * target * 4)
    if target > size:
        for y in range(target):
            sy = y * size // target
            for x in range(target):
                sx = x * size // target
                out[(y * target + x) * 4:(y * target + x) * 4 + 4] = rgba[(sy * size + sx) * 4:(sy * size + sx) * 4 + 4]
        return bytes(out)
    for y in range(target):
        y0, y1 = y * size // target, max(y * size // target + 1, (y + 1) * size // target)
        for x in range(target):
            x0, x1 = x * size // target, max(x * size // target + 1, (x + 1) * size // target)
            r = g = b = a = n = 0
            for sy in range(y0, y1):
                row = sy * size
                for sx in range(x0, x1):
                    i = (row + sx) * 4
                    pa = rgba[i + 3]
                    r += rgba[i] * pa
                    g += rgba[i + 1] * pa
                    b += rgba[i + 2] * pa
                    a += pa
                    n += 1
            i = (y * target + x) * 4
            if a:
                out[i:i + 4] = bytes((r // a, g // a, b // a, a // n))
    return bytes(out)


def default_icon(size=256):
    """A plain Viper badge: a light 'V' on a dark green rounded square."""
    out = bytearray(size * size * 4)
    radius = size * 0.18
    for y in range(size):
        for x in range(size):
            cx = min(max(x + 0.5, radius), size - radius)
            cy = min(max(y + 0.5, radius), size - radius)
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 > radius ** 2:
                continue
            u, v = (x + 0.5) / size, (y + 0.5) / size
            # Distance to the two strokes of the V.
            in_v = False
            if 0.22 <= v <= 0.78:
                t = (v - 0.22) / 0.56
                left, right = 0.24 + 0.26 * t, 0.76 - 0.26 * t
                in_v = abs(u - left) < 0.075 or abs(u - right) < 0.075
            out[(y * size + x) * 4:(y * size + x) * 4 + 4] = bytes((226, 244, 236, 255) if in_v else (22, 78, 60, 255))
    return png_encode(size, size, bytes(out))


def load_icon(path):
    """Returns (ico_entries, png_256): ico_entries is [(width, height, image bytes)].

    .png and .ico inputs both become one square RGBA image, re-rendered at every
    icon size, so odd .ico files (non-square, paletted, a single size) still work."""
    source = default_icon() if path is None else Path(path).read_bytes()
    if source[:4] == b'\0\0\1\0':
        width, height, rgba = ico_decode(source)
    else:
        width, height, rgba = png_decode(source)
    size, rgba = square(width, height, rgba)
    entries = [(n, n, png_encode(n, n, resize(size, rgba, n))) for n in ICON_SIZES]
    return entries, entries[-1][2]


def ico_decode(data):
    """Decodes the largest image of an .ico file to (width, height, rgba)."""
    count = struct.unpack('<H', data[4:6])[0]
    best = None
    for i in range(count):
        w, h, _, _, _, bits, size, offset = struct.unpack('<BBBBHHII', data[6 + 16 * i:22 + 16 * i])
        image = data[offset:offset + size]
        if len(image) != size or size < 16:
            continue
        try:
            decoded = png_decode(image) if image.startswith(b'\x89PNG') else dib_decode(image)
        except (PackageError, struct.error, zlib.error, IndexError):
            continue
        key = (decoded[0] * decoded[1], bits)
        if best is None or key > best[0]:
            best = (key, decoded)
    if best is None:
        raise PackageError('Icon .ico file has no image this exporter can read; save it as .png instead')
    return best[1]


def dib_decode(dib):
    """Decodes an .ico bitmap entry (1/4/8/24/32-bit, uncompressed) to (width, height, rgba)."""
    header, width, height2, _, bits, compression = struct.unpack('<IiiHHI', dib[:20])
    height = abs(height2) // 2  # the stored height covers the colour and mask bitmaps
    if width <= 0 or height <= 0 or bits not in (1, 4, 8, 24, 32) or compression not in (0, 3):
        raise PackageError(f'Unsupported .ico bitmap ({bits}-bit, compression {compression})')
    at = header
    if compression == 3 and header == 40:
        at += 12  # BITFIELDS masks; 32-bit icons use the usual BGRA order
    palette = []
    if bits <= 8:
        colours = struct.unpack('<I', dib[32:36])[0] or (1 << bits)
        palette = [dib[at + 4 * i:at + 4 * i + 3] for i in range(colours)]
        at += 4 * colours
    stride = (width * bits + 31) // 32 * 4
    mask_stride = (width + 31) // 32 * 4
    mask_at = at + stride * height
    has_mask = mask_at + mask_stride * height <= len(dib)
    out = bytearray(width * height * 4)
    any_alpha = False
    for y in range(height):
        row = at + (height - 1 - y) * stride  # bottom-up
        for x in range(width):
            if bits == 32:
                b, g, r, a = dib[row + 4 * x:row + 4 * x + 4]
                any_alpha |= a != 0
            elif bits == 24:
                b, g, r = dib[row + 3 * x:row + 3 * x + 3]
                a = 255
            else:
                per = 8 // bits
                index = (dib[row + x // per] >> (8 - bits * (x % per + 1))) & ((1 << bits) - 1)
                b, g, r = palette[index] if index < len(palette) else b'\0\0\0'
                a = 255
            out[(y * width + x) * 4:(y * width + x) * 4 + 4] = bytes((r, g, b, a))
    # The 1-bit AND mask marks transparent pixels (32-bit images with real alpha ignore it).
    if has_mask and not (bits == 32 and any_alpha):
        for y in range(height):
            mrow = mask_at + (height - 1 - y) * mask_stride
            for x in range(width):
                if dib[mrow + x // 8] & (0x80 >> (x % 8)):
                    out[(y * width + x) * 4 + 3] = 0
    elif bits == 32 and not any_alpha:
        for i in range(3, len(out), 4):
            out[i] = 255
    return width, height, bytes(out)


# ------------------------------------------------------------------ Windows resources

def version_node(key, value=b'', value_length=0, text=False, children=()):
    body = bytearray(struct.pack('<HHH', 0, value_length, 1 if text else 0))
    body += (key + '\0').encode('utf-16-le')
    body += b'\0' * (-len(body) % 4)
    body += value
    for child in children:
        body += b'\0' * (-len(body) % 4)
        body += child
    struct.pack_into('<H', body, 0, len(body))
    return bytes(body)


def version_info(name):
    fixed = struct.pack('<13I', 0xFEEF04BD, 0x00010000, 0x00010000, 0, 0x00010000, 0, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    strings = []
    for key, value in (('FileDescription', name), ('ProductName', name), ('InternalName', name),
                       ('OriginalFilename', safe_file_name(name) + '.exe'), ('FileVersion', '1.0.0.0'),
                       ('ProductVersion', '1.0.0.0'), ('Comments', 'Made with the Viper engine')):
        encoded = (value + '\0').encode('utf-16-le')
        strings.append(version_node(key, encoded, len(encoded) // 2, True))
    table = version_node('040904B0', text=True, children=strings)
    string_info = version_node('StringFileInfo', text=True, children=[table])
    var_info = version_node('VarFileInfo', text=True,
                            children=[version_node('Translation', struct.pack('<HH', 0x0409, 0x04B0), 4)])
    return version_node('VS_VERSION_INFO', fixed, len(fixed), children=[string_info, var_info])


MANIFEST = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3"><security><requestedPrivileges>
    <requestedExecutionLevel level="asInvoker" uiAccess="false"/>
  </requestedPrivileges></security></trustInfo>
  <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1"><application>
    <supportedOS Id="{8e0f7a12-bfb3-4fe8-b9a5-48fd50a15a9a}"/>
  </application></compatibility>
  <application xmlns="urn:schemas-microsoft-com:asm.v3"><windowsSettings>
    <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
    <dpiAwareness xmlns="http://schemas.microsoft.com/SMI/2016/WindowsSettings">PerMonitorV2</dpiAwareness>
  </windowsSettings></application>
</assembly>
'''


def resource_section(resources, base_rva):
    """Builds a .rsrc section. resources: {type_id: {name_id: bytes}}, all US English."""
    types = sorted(resources)
    # Layout: root dir, type dirs, name dirs (each with one language entry), data entries, data.
    def dir_size(n):
        return 16 + 8 * n
    offset = dir_size(len(types))
    type_at, name_at = {}, {}
    for t in types:
        type_at[t] = offset
        offset += dir_size(len(resources[t]))
    for t in types:
        for n in sorted(resources[t]):
            name_at[t, n] = offset
            offset += dir_size(1)
    entry_at = {}
    for t in types:
        for n in sorted(resources[t]):
            entry_at[t, n] = offset
            offset += 16
    data_at = {}
    for t in types:
        for n in sorted(resources[t]):
            offset += -offset % 8
            data_at[t, n] = offset
            offset += len(resources[t][n])
    out = bytearray(offset)

    def directory(at, ids, target):
        struct.pack_into('<IIHHHH', out, at, 0, 0, 0, 0, 0, len(ids))
        for i, (ident, child, subdir) in enumerate((ident, target(ident), subdir) for ident, subdir in ids):
            struct.pack_into('<II', out, at + 16 + 8 * i, ident, child | (0x80000000 if subdir else 0))

    directory(0, [(t, True) for t in types], lambda t: type_at[t])
    for t in types:
        directory(type_at[t], [(n, True) for n in sorted(resources[t])], lambda n, t=t: name_at[t, n])
        for n in sorted(resources[t]):
            directory(name_at[t, n], [(0x0409, False)], lambda _, t=t, n=n: entry_at[t, n])
            struct.pack_into('<IIII', out, entry_at[t, n], base_rva + data_at[t, n], len(resources[t][n]), 0, 0)
            out[data_at[t, n]:data_at[t, n] + len(resources[t][n])] = resources[t][n]
    return bytes(out)


def add_resources(exe, icons, name):
    """Appends a resource section (icon, version, manifest) to a PE file that has none of its own."""
    data = bytearray(exe)
    pe = struct.unpack_from('<I', data, 0x3C)[0]
    if data[pe:pe + 4] != b'PE\0\0':
        raise PackageError('Windows launcher is not a PE file')
    sections, opt_size = struct.unpack_from('<H', data, pe + 6)[0], struct.unpack_from('<H', data, pe + 20)[0]
    opt = pe + 24
    if struct.unpack_from('<H', data, opt)[0] != 0x20B:
        raise PackageError('Windows launcher must be 64-bit')
    section_align, file_align = struct.unpack_from('<II', data, opt + 32)
    headers_size = struct.unpack_from('<I', data, opt + 60)[0]
    table = opt + opt_size
    last = table + 40 * (sections - 1)
    if table + 40 * (sections + 1) > headers_size:
        raise PackageError('Windows launcher has no room for an icon section')
    if struct.unpack_from('<I', data, pe + 12)[0]:
        raise PackageError('Windows launcher must be stripped (it has a symbol table)')
    last_vsize, last_va = struct.unpack_from('<II', data, last + 8)
    align = lambda v, a: (v + a - 1) // a * a
    rva = align(last_va + last_vsize, section_align)
    raw_at = align(len(data), file_align)

    group = struct.pack('<HHH', 0, 1, len(icons))
    resources = {3: {}, 14: {}, 16: {1: version_info(name)}, 24: {1: MANIFEST}}
    for i, (w, h, image) in enumerate(icons, 1):
        resources[3][i] = image
        group += struct.pack('<BBBBHHIH', w % 256, h % 256, 0, 0, 1, 32, len(image), i)
    resources[14][1] = group
    section = resource_section(resources, rva)
    raw = section + b'\0' * (-len(section) % file_align)

    struct.pack_into('<8sIIIIIIHHI', data, table + 40 * sections, b'.rsrc', len(section), rva, len(raw), raw_at,
                     0, 0, 0, 0, 0x40000040)
    struct.pack_into('<H', data, pe + 6, sections + 1)
    struct.pack_into('<I', data, opt + 56, align(rva + len(section), section_align))  # SizeOfImage
    struct.pack_into('<I', data, opt + 64, 0)  # CheckSum (unused for applications)
    init = struct.unpack_from('<I', data, opt + 8)[0]
    struct.pack_into('<I', data, opt + 8, init + len(raw))  # SizeOfInitializedData
    struct.pack_into('<II', data, opt + 112 + 8 * 2, rva, len(section))  # resource data directory
    data += b'\0' * (raw_at - len(data))
    return bytes(data + raw)


# ------------------------------------------------------------------ payload

def safe_file_name(name):
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip(' .')
    return cleaned or 'Game'


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-') or 'game'


def game_settings(folder):
    try:
        return json.loads((folder / 'game.json').read_text(encoding='utf-8')).get('settings') or {}
    except (OSError, ValueError, AttributeError):
        return {}


def html_title(text):
    match = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
    return html_lib.unescape(match.group(1)).strip() if match else ''


def collect(folder, exclude):
    files = []
    for root, dirs, names in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not (Path(root) / d).is_symlink())
        for name in sorted(names):
            path = Path(root) / name
            if path.is_symlink() or any(path == e or e in path.parents for e in exclude):
                continue
            files.append((path.relative_to(folder).as_posix(), path))
    return files


def build_payload(items):
    out = bytearray(b'VPAK' + struct.pack('<II', 1, len(items)))
    for name, data in items:
        encoded = name.encode('utf-8')
        out += struct.pack('<I', len(encoded)) + encoded + struct.pack('<Q', len(data)) + data
    return bytes(out)


def package(html, output, target, icon=None, name=None, width=None, height=None, fullscreen=False, fixed_size=False):
    html = Path(html).resolve()
    if target not in LAUNCHERS:
        raise PackageError(f'Unknown target: {target}')
    if not html.is_file() or html.suffix.lower() not in ('.html', '.htm'):
        raise PackageError(f'Choose the game\'s HTML file: {html}')
    launcher = LAUNCHERS[target]
    if not launcher.is_file():
        raise PackageError(f'Launcher missing: {launcher}. Run exporter/desktop/build_launchers.sh')
    folder = html.parent
    page = html.read_text(encoding='utf-8', errors='replace')
    settings = game_settings(folder)
    name = (name or '').strip() or str(settings.get('title') or '').strip() or html_title(page) or folder.name
    name = re.sub(r'[\r\n]+', ' ', name)
    width = int(width or settings.get('width') or 1280)
    height = int(height or settings.get('height') or 720)
    game_id = slug(name)
    port = 20000 + zlib.crc32(game_id.encode()) % 30000

    output = Path(output).resolve()
    executable = output / (safe_file_name(name) + ('.exe' if target == 'windows' else ''))
    items = []
    for rel, path in collect(folder, exclude=[output, executable]):
        if rel.startswith('__viper/'):
            continue
        data = path.read_bytes()
        if path == html:
            # The window title comes from the page.
            title = f'<title>{html_lib.escape(name)}</title>'
            text, count = re.subn(r'<title[^>]*>.*?</title>', lambda _: title, page, count=1, flags=re.I | re.S)
            if not count:
                text = re.sub(r'(<head[^>]*>)', lambda m: m.group(1) + title, text, count=1, flags=re.I)
            data = text.encode('utf-8')
        items.append((rel, data))
    ico, png = load_icon(icon)
    cfg = (f'name={name}\nid={game_id}\nstart={html.relative_to(folder).as_posix()}\nport={port}\n'
           f'width={width}\nheight={height}\nfullscreen={int(fullscreen)}\nfixed_size={int(fixed_size)}\n')
    items += [('__viper/launcher.cfg', cfg.encode('utf-8')), ('__viper/icon.png', png)]
    payload = build_payload(items)

    stub = launcher.read_bytes()
    if target == 'windows':
        stub = add_resources(stub, ico, name)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output, delete=False) as tmp:
        tmp.write(stub + payload + struct.pack('<QQ', len(stub), len(payload)) + b'VIPERPK1')
    os.chmod(tmp.name, 0o755)
    os.replace(tmp.name, executable)
    if target == 'linux':
        show_linux_icon(executable, game_id, png)
    return executable, len(items) - 2


def show_linux_icon(executable, game_id, png):
    """Shows the icon on the exported file in this machine's file manager.

    Linux executables carry no icon, so this uses the same GIO file metadata the
    launcher sets on each start (on other machines it applies after the first run).
    The icon lives with the game's data, not beside the app."""
    gio = shutil.which('gio')
    if not sys.platform.startswith('linux') or not gio:
        return
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    icon = base / 'viper-games' / game_id / 'icon.png'
    try:
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes(png)
        subprocess.run([gio, 'set', str(executable), 'metadata::custom-icon', icon.as_uri()],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--html', type=Path, required=True, help='the game page, usually index.html of a web export')
    parser.add_argument('--icon', type=Path, help='a .png or .ico file (a default icon is used when omitted)')
    parser.add_argument('--output', type=Path, required=True, help='folder to write the app into')
    parser.add_argument('--target', choices=sorted(LAUNCHERS), required=True)
    parser.add_argument('--name', help='app and window name (default: the game title)')
    parser.add_argument('--width', type=int)
    parser.add_argument('--height', type=int)
    parser.add_argument('--fullscreen', action='store_true', help='start in full screen')
    parser.add_argument('--fixed-size', action='store_true', help='players cannot resize the window')
    args = parser.parse_args()
    try:
        if args.icon is not None and not args.icon.is_file():
            raise PackageError(f'Icon not found: {args.icon}')
        executable, count = package(args.html, args.output, args.target, args.icon, args.name, args.width,
                                    args.height, args.fullscreen, args.fixed_size)
    except (PackageError, OSError, zlib.error, struct.error) as error:
        print(f'Packaging failed: {error}', file=sys.stderr)
        return 1
    print(f'Packaged {args.target}: {executable} ({count} files)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
