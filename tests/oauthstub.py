"""A small OAuth 2 server for the tests (Google's and Microsoft's installed-app flow): the sign-in page
sends the browser straight back to the loopback address with a code; the token endpoint checks the
PKCE verifier and the client, and hands out "test-token" (which the test mail servers accept)."""
import base64
import hashlib
import http.server
import json
import threading
import urllib.parse


class World:
    def __init__(self, client_id="123-abc.apps.googleusercontent.com", secret="s3cret"):
        self.client_id, self.secret = client_id, secret
        self.codes = {}
        self.log = []


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, d):
        b = json.dumps(d).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        w = self.server.world
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path != "/auth":
            return self._json(404, {})
        w.log.append(("auth", q))
        if q.get("client_id") != w.client_id:
            loc = q["redirect_uri"] + "?" + urllib.parse.urlencode({"error": "invalid_client", "state": q.get("state", "")})
        else:
            code = "code-%d" % len(w.codes)
            w.codes[code] = q.get("code_challenge", "")
            loc = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q.get("state", "")})
        self.send_response(302)
        self.send_header("Location", loc)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        w = self.server.world
        q = {k: v[0] for k, v in urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        w.log.append(("token", q))
        if q.get("client_id") != w.client_id or q.get("client_secret", "") != w.secret:
            return self._json(401, {"error": "invalid_client"})
        if q.get("grant_type") == "refresh_token":
            return self._json(200, {"access_token": "test-token", "expires_in": 3600})
        chal = w.codes.pop(q.get("code", ""), None)
        want = base64.urlsafe_b64encode(hashlib.sha256(q.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
        if chal is None or chal != want:
            return self._json(400, {"error": "invalid_grant"})
        return self._json(200, {"access_token": "test-token", "refresh_token": "refresh-1", "expires_in": 3600})


def start(world=None):
    world = world or World()
    s = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    s.world = world
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return world, "http://127.0.0.1:%d" % s.server_address[1], s.shutdown
