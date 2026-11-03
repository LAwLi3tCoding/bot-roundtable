"""Bounded single-use login codes and renewable, restricted UI sessions."""

from collections import deque
import hashlib
import re
import secrets
import threading
import time

from roundtable import Problem


class UISessions:
    def __init__(self, clock=time.monotonic, code_seconds=60, session_seconds=3600):
        self.clock = clock
        self.code_seconds = code_seconds
        self.session_seconds = session_seconds
        self.codes = {}
        self.sessions = {}
        self.issues: deque[float] = deque(maxlen=16)
        self.failures: deque[float] = deque(maxlen=20)
        self.lock = threading.Lock()

    def _cleanup(self):
        now = self.clock()
        self.codes = {k: v for k, v in self.codes.items() if v > now}
        self.sessions = {k: v for k, v in self.sessions.items() if v > now}
        for queue in (self.issues, self.failures):
            while queue and queue[0] <= now - 60:
                queue.popleft()
        return now

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    @staticmethod
    def boundary(peer, host, origin, port, exchange=False):
        expected = f"127.0.0.1:{port}"
        if (
            peer != "127.0.0.1"
            or host != expected
            or (exchange and origin != f"http://{expected}")
            or (origin is not None and origin != f"http://{expected}")
        ):
            raise Problem(403, "UI login origin rejected")

    def issue(self):
        with self.lock:
            now = self._cleanup()
            if len(self.codes) >= 16 or len(self.issues) >= 16:
                raise Problem(429, "UI login temporarily unavailable")
            code = secrets.token_urlsafe(32)
            self.codes[self.digest(code)] = now + self.code_seconds
            self.issues.append(now)
            return {"code": code, "expires_in": self.code_seconds}

    def exchange(self, code):
        with self.lock:
            now = self._cleanup()
            if len(self.failures) >= 20 or len(self.sessions) >= 32:
                raise Problem(429, "UI login temporarily unavailable")
            if (
                not isinstance(code, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code)
                or self.digest(code) not in self.codes
            ):
                self.failures.append(now)
                raise Problem(403, "UI login code invalid")
            del self.codes[self.digest(code)]
            token = "ui_" + secrets.token_urlsafe(32)
            self.sessions[self.digest(token)] = now + self.session_seconds
            return {"session_token": token, "expires_in": self.session_seconds, "temporary": True}

    def valid(self, token):
        if not isinstance(token, str) or not re.fullmatch(r"ui_[A-Za-z0-9_-]{43}", token):
            return False
        with self.lock:
            self._cleanup()
            return self.digest(token) in self.sessions

    def renew(self, token):
        with self.lock:
            now = self._cleanup()
            key = self.digest(token)
            if key not in self.sessions:
                raise Problem(403, "UI session expired")
            self.sessions[key] = now + self.session_seconds
            return {"expires_in": self.session_seconds, "temporary": True}

    def revoke(self, token):
        with self.lock:
            self.sessions.pop(self.digest(token), None)

    @staticmethod
    def permitted(method, path):
        # Credential issuance and membership administration remain forbidden.
        if method == "GET":
            return path in ("/api/rooms", "/api/bots") or bool(
                re.fullmatch(r"/api/rooms/[a-f0-9]{24}(?:/connections|/tasks|/topics)?", path)
            )
        return method == "POST" and bool(
            re.fullmatch(
                r"/api/rooms/[a-f0-9]{24}/(?:tasks(?:/(?:query|context|cancel|retry))?|topics(?:/(?:query|messages|inbox|read|stop|update|roundtable))?|runs|stop|grant|settings)",
                path,
            )
        )
