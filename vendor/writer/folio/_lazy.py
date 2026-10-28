"""Modules that need the old engine (UNO), imported only when first used, so the
new engine runs without LibreOffice installed."""
import importlib


class Lazy:
    def __init__(self, name):
        self._name = name
        self._mod = None

    def __getattr__(self, k):
        if self._mod is None:
            self._mod = importlib.import_module(self._name)
        return getattr(self._mod, k)


bridge = Lazy("folio.bridge")
docapi = Lazy("folio.docapi")
uno = Lazy("uno")
