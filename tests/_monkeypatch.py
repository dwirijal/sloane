"""Minimal monkeypatch shim so tests run without pytest.

Mirrors pytest's monkeypatch.setattr — records originals, restores on undo().
Usage in stdlib test runner: mp = MonkeyPatch(); mp.setattr("a.b", fn);
... run test ...; mp.undo()
"""
import importlib


class MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, value=None):
        # 3-arg object form: setattr(obj, name, value)
        if not isinstance(target, str) and isinstance(target, tuple) and len(target) == 2:
            obj, name = target
            orig = getattr(obj, name)
            self._undo.append((obj, name, orig))
            setattr(obj, name, value)
            return
        # dotted-string form: setattr("pkg.mod.attr", value)
        mod_path, _, attr = target.rpartition(".")
        mod = importlib.import_module(mod_path)
        orig = getattr(mod, attr)
        self._undo.append((mod, attr, orig))
        setattr(mod, attr, value)

    def undo(self):
        for obj, attr, orig in reversed(self._undo):
            setattr(obj, attr, orig)
        self._undo.clear()
