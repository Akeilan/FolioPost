"""Signing in with Google in the browser (OAuth 2 for installed apps: the browser comes back to
a one-time address on this computer with the code; PKCE, no secret kept anywhere else).
Google needs an OAuth client ID for the app, made once in the Google Cloud console under the
user's own Google account (Desktop app type); Post keeps it in its settings."""
import base64
import hashlib
import http.server
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request

MS_AUTH = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
MS_TOKEN = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
MS_SCOPES = ["https://outlook.office.com/IMAP.AccessAsUser.All", "https://outlook.office.com/SMTP.Send",
             "https://outlook.office.com/EWS.AccessAsUser.All", "offline_access",
             "openid", "email"]
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_SCOPES = ["https://mail.google.com/", "https://www.googleapis.com/auth/calendar",
                 "https://www.googleapis.com/auth/gmail.settings.basic",
                 "https://www.googleapis.com/auth/carddav", "openid", "email"]


class _Catch(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.server.result = {k: v[0] for k, v in q.items()}
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        ok = "code" in self.server.result
        self.wfile.write(("<html><body style='font-family:sans-serif;padding:40px'><h2>%s</h2><p>You can close this "
                          "window and go back to Folio Post.</p></body></html>" %
                          ("Signed in" if ok else "Sign-in didn't finish")).encode())

    def log_message(self, *a):
        pass


def endpoints(provider):
    if provider == "microsoft":
        return MS_AUTH, MS_TOKEN, MS_SCOPES
    return GOOGLE_AUTH, GOOGLE_TOKEN, GOOGLE_SCOPES


def auth_url(client_id, redirect, challenge, state, login_hint="", provider="google"):
    auth, _tok, scopes = endpoints(provider)
    q = {"client_id": client_id, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(scopes),
         "code_challenge": challenge, "code_challenge_method": "S256", "state": state}
    if provider == "google":
        q.update({"access_type": "offline", "prompt": "consent"})
    else:
        q["prompt"] = "select_account"
    if login_hint:
        q["login_hint"] = login_hint
    return auth + "?" + urllib.parse.urlencode(q)


def sign_in(client_id, client_secret="", open_url=None, timeout=300, login_hint="", provider="google"):
    """The browser sign-in; returns tokens {access_token, refresh_token, expires_at}."""
    srv = http.server.HTTPServer(("127.0.0.1", 0), _Catch)
    srv.result = None
    redirect = "http://127.0.0.1:%d/" % srv.server_address[1]
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    url = auth_url(client_id, redirect, challenge, state, login_hint, provider)
    t = threading.Thread(target=lambda: _serve(srv, timeout), daemon=True)
    t.start()
    (open_url or _open)(url)
    t.join(timeout + 5)
    srv.server_close()
    r = srv.result or {}
    if r.get("state") != state or "code" not in r:
        raise RuntimeError(r.get("error", "the sign-in was cancelled"))
    data = {"code": r["code"], "client_id": client_id, "redirect_uri": redirect, "grant_type": "authorization_code",
            "code_verifier": verifier}
    if client_secret:
        data["client_secret"] = client_secret
    return _token(data, provider)


def _serve(srv, timeout):
    end = time.time() + timeout
    srv.timeout = 1
    while srv.result is None and time.time() < end:
        srv.handle_request()


def _open(url):
    import subprocess
    subprocess.Popen(["xdg-open", url])


def _token(data, provider="google"):
    req = urllib.request.Request(endpoints(provider)[1], data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        t = json.loads(resp.read().decode())
    t["expires_at"] = time.time() + int(t.get("expires_in", 3600)) - 60
    return t


def refresh(client_id, client_secret, tokens, provider="google"):
    data = {"client_id": client_id, "refresh_token": tokens["refresh_token"], "grant_type": "refresh_token"}
    if client_secret:
        data["client_secret"] = client_secret
    t = _token(data, provider)
    t.setdefault("refresh_token", tokens["refresh_token"])
    return t


def built_in_client(provider):
    """share/folio-post/<provider>-client.json: a client ID the package ships with, so nobody has to make one."""
    import json as _j
    from . import SHARE
    for d in (SHARE, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "share")):
        try:
            with open(os.path.join(d, "%s-client.json" % provider)) as fh:
                return _j.load(fh)
        except (OSError, ValueError):
            continue
    return {}


class TokenSource:
    """Access tokens for OAuth accounts, refreshed when they run out."""

    def __init__(self, store, secrets_):
        self.store = store
        self.secrets = secrets_

    def client(self, provider="google"):
        """The OAuth client: one kept in settings, from the environment, or built into the package."""
        c = self.store.get("%s-client" % provider, {}) or {}
        env = os.environ.get("FOLIO_POST_%s_CLIENT_ID" % provider.upper(), "")
        built = built_in_client(provider)
        cid = c.get("id") or env or built.get("id", "")
        sec = c.get("secret") or os.environ.get("FOLIO_POST_%s_CLIENT_SECRET" % provider.upper(), "") or built.get("secret", "")
        return cid, sec

    def __call__(self, acc):
        if acc["config"].get("auth") == "goa":
            from . import goa
            return goa.token(acc["config"]["goa_id"])
        raw = self.secrets.get(acc["id"], "oauth")
        if not raw:
            raise RuntimeError("this account needs signing in again")
        tokens = json.loads(raw)
        if tokens.get("expires_at", 0) < time.time() and tokens.get("refresh_token"):
            provider = acc["config"].get("oauth_provider", "google")
            cid, sec = self.client(provider)
            tokens = refresh(cid, sec, tokens, provider)
            self.secrets.set(acc["id"], json.dumps(tokens), "oauth")
        return tokens["access_token"]
