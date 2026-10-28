import sys
from gi.repository import Gtk
print("window", win.get_title())
print("tabs", [t.name for t in win.ribbon.tabs])
sys.stdout.flush()
import os
os._exit(0)
