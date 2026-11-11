"""Embedded document faces with per-character fallback for limited GB2312 fonts."""
import logging
import os
import threading
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFError

FONT_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'fonts'
font_lock = threading.Lock()


def font_path():
    candidates = [os.getenv('PDF_FONT_PATH', ''),
                  '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
                  '/System/Library/Fonts/STHeiti Light.ttc',
                  str(FONT_DIR / 'FangSong_GB2312.ttf')]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise RuntimeError('未找到可嵌入的中文字体，请配置 PDF_FONT_PATH')


def font_name():
    with font_lock:
        if 'LeaveChinese' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('LeaveChinese', font_path()))
    return 'LeaveChinese'


def document_font_candidates(kind):
    if kind == 'body':
        return [os.getenv('PDF_BODY_FONT_PATH', ''), str(FONT_DIR / 'FangSong_GB2312.ttf'),
                '/usr/share/fonts/truetype/arphic/uming.ttc',
                '/System/Library/Fonts/Supplemental/Songti.ttc']
    return [os.getenv('PDF_TITLE_FONT_PATH', ''), str(FONT_DIR / 'FZXiaoBiaoSong.ttf'),
            '/System/Library/Fonts/STHeiti Medium.ttc']


def document_font(kind):
    name = 'LeaveDocumentBody' if kind == 'body' else 'LeaveDocumentHeading'
    with font_lock:
        if name in pdfmetrics.getRegisteredFontNames():
            return name
        for path in document_font_candidates(kind):
            if not path or not Path(path).is_file():
                continue
            # Apple's Songti collection starts with Black; index 6 is SC Regular.
            subfont = 6 if path == '/System/Library/Fonts/Supplemental/Songti.ttc' else 0
            try:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont))
                return name
            except (TTFError, OSError, ValueError):
                logging.getLogger(__name__).warning('文书字体无法载入，尝试回退字体：%s', path)
    return font_name()


def paragraph_text(text, primary):
    """Escape user text and switch only unsupported glyphs to the general CJK face."""
    glyphs = pdfmetrics.getFont(primary).face.charToGlyph
    runs = []
    current = []
    current_font = primary
    fallback = None
    for char in str(text):
        target = primary
        if char not in '\n\r\t' and not glyphs.get(ord(char)):
            fallback = fallback or font_name()
            target = fallback
        if target != current_font and current:
            runs.append((current_font, ''.join(current)))
            current = []
        current_font = target
        current.append(char)
    if current:
        runs.append((current_font, ''.join(current)))
    result = []
    for face, value in runs:
        value = escape(value).replace('\n', '<br/>')
        result.append(value if face == primary else f'<font name="{face}">{value}</font>')
    return ''.join(result)
