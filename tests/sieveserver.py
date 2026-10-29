"""A small ManageSieve server (RFC 5804) for the tests: scripts in memory, PLAIN sign-in, and a
check that scripts use only what the server says it has."""
import base64
import re
import socketserver
import threading


class World:
    def __init__(self):
        self.users = {}            # user -> {"password", "scripts": {name: text}, "active": name}
        self.log = []

    def add_user(self, user, password):
        self.users[user] = {"password": password, "scripts": {}, "active": None}
        return self.users[user]


CAPS = ['"IMPLEMENTATION" "Folio test Sieve"', '"SASL" "PLAIN"', '"SIEVE" "fileinto vacation date relational envelope"',
        '"VERSION" "1.0"']


class Handler(socketserver.StreamRequestHandler):
    def out(self, s):
        self.wfile.write((s + "\r\n").encode())

    def handle(self):
        w = self.server.world
        for c in CAPS:
            self.out(c)
        self.out('OK "ready"')
        user = None
        while True:
            ln = self.rfile.readline()
            if not ln:
                return
            ln = ln.decode().rstrip("\r\n")
            w.log.append(ln.split(" ")[0])
            m = re.match(r'^(\w+)\s*(.*)$', ln)
            cmd, rest = m.group(1).upper(), m.group(2)
            if cmd == "AUTHENTICATE":
                tok = re.findall(r'"([^"]*)"', rest)[1]
                _z, u, p = base64.b64decode(tok).decode().split("\0")
                if u in w.users and w.users[u]["password"] == p:
                    user = w.users[u]
                    self.out("OK")
                else:
                    self.out('NO "Authentication failed"')
            elif cmd == "LOGOUT":
                self.out("OK")
                return
            elif user is None:
                self.out('NO "Sign in first"')
            elif cmd == "LISTSCRIPTS":
                for n in user["scripts"]:
                    self.out('"%s"%s' % (n, " ACTIVE" if n == user["active"] else ""))
                self.out("OK")
            elif cmd == "GETSCRIPT":
                n = re.findall(r'"([^"]*)"', rest)[0]
                if n not in user["scripts"]:
                    self.out('NO (NONEXISTENT) "no such script"')
                    continue
                b = user["scripts"][n].encode()
                self.wfile.write(b"{%d}\r\n" % len(b) + b + b"\r\n")
                self.out("OK")
            elif cmd == "PUTSCRIPT":
                n = re.findall(r'"([^"]*)"', rest)[0]
                size = int(re.search(r"\{(\d+)\+?\}", rest).group(1))
                body = self.rfile.read(size).decode()
                self.rfile.readline()
                req = set(x for r in re.findall(r"require\s*\[([^\]]*)\]", body) for x in re.findall(r'"([^"]+)"', r))
                if not req <= {"fileinto", "vacation", "date", "relational", "envelope"} or body.count("{") != body.count("}"):
                    self.out('NO "script error"')
                    continue
                user["scripts"][n] = body
                self.out("OK")
            elif cmd == "SETACTIVE":
                user["active"] = re.findall(r'"([^"]*)"', rest)[0] or None
                self.out("OK")
            else:
                self.out('NO "unknown command"')


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(world):
    s = Server(("127.0.0.1", 0), Handler)
    s.world = world
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]
