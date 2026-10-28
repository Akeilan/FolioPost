import os, sys, time
from gi.repository import Gtk
exec(open(os.path.join(os.environ["FOLIO_TESTS"], "ui_mail.py")).read().split("try:\n    store = app.store")[0])
sys.path.insert(0, os.environ["FOLIO_TESTS"])
import mailserver
world = mailserver.World(); boxes = world.add_user("me@example.org", "secret")
for i in range(6):
    boxes["INBOX"].add(mailserver.sample(i, html=i == 0, attach=i == 2))
_w, ip, sp, stop = mailserver.start(world)
cfg = {"imap_host": "127.0.0.1", "imap_port": ip, "imap_security": "none", "smtp_host": "127.0.0.1", "smtp_port": sp,
       "smtp_security": "none", "user": "me@example.org"}
from folio_post.accounts import create_account
aid = create_account(win, "Me", "me@example.org", cfg, "secret")
wait(lambda: len(win.iter_rows()) == 6, 20)
win.select_ids([win.iter_rows()[0][0]]); pump(0.5)
shot(win, "dark")
os._exit(0)
