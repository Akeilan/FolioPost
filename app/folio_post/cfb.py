"""Compound File Binary (the "OLE" container Office uses for password-protected files, .msg and
.oft): reading and writing streams and storages, written from [MS-CFB] (version 3, 512-byte
sectors)."""
import struct

SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
FREE, END, FATSECT, DIFSECT = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD, 0xFFFFFFFC
NOSTREAM = 0xFFFFFFFF
SECTOR, MINI, CUTOFF = 512, 64, 4096


def is_cfb(data):
    return data[:8] == SIG


# ---------------------------------------------------------------- reading
class Reader:
    """Read a compound file: `streams()` gives {"Storage/Stream": bytes}."""
    def __init__(self, data):
        if not is_cfb(data):
            raise ValueError("not a compound file")
        self.data = data
        h = data[:512]
        self.shift = struct.unpack_from("<H", h, 30)[0]
        self.ssize = 1 << self.shift
        self.mshift = struct.unpack_from("<H", h, 32)[0]
        nfat, first_dir = struct.unpack_from("<II", h, 44)
        self.cutoff, first_mfat, nmfat, first_difat, ndifat = struct.unpack_from("<IIIII", h, 56)
        difat = list(struct.unpack_from("<109I", h, 76))
        s = first_difat
        while s not in (END, FREE) and ndifat > 0:
            blk = self._sector(s)
            n = self.ssize // 4 - 1
            difat += list(struct.unpack_from("<%dI" % n, blk, 0))
            s = struct.unpack_from("<I", blk, n * 4)[0]
            ndifat -= 1
        self.fat = []
        for sec in difat[:nfat]:
            if sec in (FREE, END):
                continue
            self.fat += list(struct.unpack("<%dI" % (self.ssize // 4), self._sector(sec)))
        dirdata = self._chain(first_dir)
        self.entries = []
        for k in range(len(dirdata) // 128):
            e = dirdata[k * 128:(k + 1) * 128]
            nlen = struct.unpack_from("<H", e, 64)[0]
            name = e[:max(0, nlen - 2)].decode("utf-16-le", "replace")
            typ = e[66]
            left, right, child = struct.unpack_from("<III", e, 68)
            start = struct.unpack_from("<I", e, 116)[0]
            size = struct.unpack_from("<Q", e, 120)[0]
            if self.shift == 9:
                size &= 0xFFFFFFFF
            self.entries.append(dict(name=name, type=typ, left=left, right=right, child=child, start=start, size=size))
        root = self.entries[0]
        self.ministream = self._chain(root["start"])[:root["size"]] if root["start"] not in (END, FREE) else b""
        self.minifat = []
        if first_mfat not in (END, FREE):
            mf = self._chain(first_mfat)
            self.minifat = list(struct.unpack("<%dI" % (len(mf) // 4), mf))

    def _sector(self, s):
        off = (s + 1) * self.ssize
        return self.data[off:off + self.ssize]

    def _chain(self, s):
        out = []
        seen = set()
        while s not in (END, FREE) and s < len(self.fat) and s not in seen:
            seen.add(s)
            out.append(self._sector(s))
            s = self.fat[s]
        return b"".join(out)

    def _mini_chain(self, s, size):
        out = []
        seen = set()
        ms = 1 << self.mshift
        while s not in (END, FREE) and s < len(self.minifat) and s not in seen:
            seen.add(s)
            out.append(self.ministream[s * ms:(s + 1) * ms])
            s = self.minifat[s]
        return b"".join(out)[:size]

    def read_entry(self, e):
        if e["size"] < self.cutoff:
            return self._mini_chain(e["start"], e["size"])
        return self._chain(e["start"])[:e["size"]]

    def streams(self):
        out = {}

        def walk(idx, prefix, depth=0):
            if idx == NOSTREAM or idx >= len(self.entries) or depth > 64:
                return
            e = self.entries[idx]
            walk(e["left"], prefix, depth + 1)
            path = prefix + e["name"]
            if e["type"] == 2:
                out[path] = self.read_entry(e)
            elif e["type"] == 1:
                walk(e["child"], path + "/", depth + 1)
            walk(e["right"], prefix, depth + 1)
        walk(self.entries[0]["child"], "")
        return out


def read(data):
    return Reader(data).streams()


# ---------------------------------------------------------------- writing
def _key(name):
    return (len(name), name.upper())


def write(streams):
    """A compound file from {"Storage/Sub/Stream": bytes} (storages are made as needed)."""
    # the tree of storages
    root = {"name": "Root Entry", "type": 5, "kids": {}, "data": b""}
    for path, data in streams.items():
        parts = path.split("/")
        node = root
        for p in parts[:-1]:
            node = node["kids"].setdefault(p, {"name": p, "type": 1, "kids": {}, "data": b""})
        node["kids"][parts[-1]] = {"name": parts[-1], "type": 2, "kids": {}, "data": bytes(data)}
    entries = []

    def add(node):
        node["id"] = len(entries)
        entries.append(node)
        kids = sorted(node["kids"].values(), key=lambda n: _key(n["name"]))
        for k in kids:
            add(k)
        node["sorted"] = kids
    add(root)

    # each storage's children as a balanced tree, red only on the deepest level when needed
    for node in entries:
        for k in node["sorted"]:
            k.setdefault("left", NOSTREAM)
            k.setdefault("right", NOSTREAM)
            k["color"] = 1
        kids = node["sorted"]
        if not kids:
            node["child"] = NOSTREAM
            continue
        import math
        depth_of = {}

        def build(lo, hi, d):
            if lo > hi:
                return NOSTREAM
            mid = (lo + hi) // 2
            n = kids[mid]
            depth_of[mid] = d
            n["left"] = build(lo, mid - 1, d + 1)
            n["right"] = build(mid + 1, hi, d + 1)
            return n["id"]
        node["child"] = build(0, len(kids) - 1, 0)
        maxd = max(depth_of.values())
        perfect = len(kids) == 2 ** (maxd + 1) - 1
        if not perfect:
            for k, d in depth_of.items():
                if d == maxd:
                    kids[k]["color"] = 0
        _ = math
    for e in entries:
        e.setdefault("left", NOSTREAM)
        e.setdefault("right", NOSTREAM)
        e.setdefault("color", 1)

    sectors = []          # regular sectors' bytes
    fat = []

    def put_chain(data, mark=None):
        if not data:
            return END
        n = (len(data) + SECTOR - 1) // SECTOR
        first = len(sectors)
        for k in range(n):
            blk = data[k * SECTOR:(k + 1) * SECTOR]
            sectors.append(blk + b"\0" * (SECTOR - len(blk)))
            fat.append(first + k + 1 if k < n - 1 else END)
        return first

    # small streams into the mini stream
    mini = bytearray()
    minifat = []
    for e in entries:
        if e["type"] != 2:
            continue
        d = e["data"]
        e["size"] = len(d)
        if len(d) < CUTOFF:
            if not d:
                e["start"] = END
                continue
            n = (len(d) + MINI - 1) // MINI
            first = len(minifat)
            for k in range(n):
                blk = d[k * MINI:(k + 1) * MINI]
                mini += blk + b"\0" * (MINI - len(blk))
                minifat.append(first + k + 1 if k < n - 1 else END)
            e["start"] = first
    for e in entries:
        if e["type"] == 2 and len(e["data"]) >= CUTOFF:
            e["start"] = put_chain(e["data"])
    root["start"] = put_chain(bytes(mini)) if mini else END
    root["size"] = len(mini)
    mfat_bytes = b"".join(struct.pack("<I", v) for v in minifat)
    first_mfat = put_chain(mfat_bytes) if minifat else END
    nmfat = (len(mfat_bytes) + SECTOR - 1) // SECTOR
    # the directory
    d = bytearray()
    for e in entries:
        name = e["name"].encode("utf-16-le")[:62]
        rec = bytearray(128)
        rec[:len(name)] = name
        struct.pack_into("<H", rec, 64, len(name) + 2)
        rec[66] = e["type"]
        rec[67] = e["color"]
        struct.pack_into("<III", rec, 68, e["left"], e["right"], e.get("child", NOSTREAM) if e["type"] != 2 else NOSTREAM)
        struct.pack_into("<I", rec, 116, e.get("start", END) if e["type"] != 1 else 0)
        struct.pack_into("<Q", rec, 120, e.get("size", 0) if e["type"] != 1 else 0)
        d += rec
    while len(d) % SECTOR:
        d += b"\0" * 128
        struct.pack_into("<III", d, len(d) - 128 + 68, NOSTREAM, NOSTREAM, NOSTREAM)
    first_dir = put_chain(bytes(d))
    # the FAT itself (its sectors marked FATSECT)
    nfat = 1
    while True:
        total = len(sectors) + nfat
        if total <= nfat * (SECTOR // 4):
            break
        nfat += 1
    if nfat > 109:
        raise ValueError("compound file too large")
    fat_start = len(sectors)
    fat += [FATSECT] * nfat
    fat += [FREE] * (nfat * (SECTOR // 4) - len(fat))
    fat_bytes = b"".join(struct.pack("<I", v) for v in fat)
    for k in range(nfat):
        sectors.append(fat_bytes[k * SECTOR:(k + 1) * SECTOR])
    h = bytearray(512)
    h[:8] = SIG
    struct.pack_into("<HHHHHH", h, 24, 0x3E, 3, 0xFFFE, 9, 6, 0)
    struct.pack_into("<IIII", h, 40, 0, nfat, first_dir, 0)
    struct.pack_into("<IIIII", h, 56, CUTOFF, first_mfat, nmfat, END, 0)
    difat = [fat_start + k for k in range(nfat)] + [FREE] * (109 - nfat)
    struct.pack_into("<109I", h, 76, *difat)
    return bytes(h) + b"".join(sectors)
