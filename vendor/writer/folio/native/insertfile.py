"""Insert > Object > Text from File with the new engine: a .docx's body comes in with its
formatting; .txt as text; .html through the HTML reader; other formats (.doc, .odt, .rtf)
are converted to .docx first."""
import os
import shutil
import subprocess
import tempfile

from . import core


def _docx_body(path):
    other = core().Editor.open(path)
    other.select_all()
    return other.copy_fragment()


def insert(win, path):
    ed = win.engine.ed
    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".text", ".csv"):
        with open(path, encoding="utf-8", errors="replace") as f:
            ed.type_text(f.read().replace("\r\n", "\n"))
        win.engine.view.after_edit()
        return
    if ext in (".htm", ".html"):
        with open(path, "rb") as f:
            win.engine.paste_html(f.read())
        return
    tmp = None
    try:
        if ext not in (".docx", ".docm", ".dotx", ".dotm"):
            tmp = tempfile.mkdtemp(prefix="folio-insert-")
            r = subprocess.run(["soffice", "--headless", "--convert-to", "docx", "--outdir", tmp, path],
                               capture_output=True, timeout=120)
            out = os.path.join(tmp, os.path.splitext(os.path.basename(path))[0] + ".docx")
            if r.returncode != 0 or not os.path.exists(out):
                raise ValueError("it couldn't be converted")
            path = out
        xml = _docx_body(path)
        if xml:
            ed.paste_fragment(xml, False)
        win.engine.view.after_edit()
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
