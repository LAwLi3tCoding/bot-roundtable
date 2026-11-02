# Restricted local browser sessions

Opening an unauthenticated HTTP homepage does not issue a session. A loopback socket peer and matching Host/Origin cannot distinguish a browser from an arbitrary transparent local proxy. The safe default therefore retains the credential-backed `local_runtime.py ui` launch and manual token fallback. No new setting is enabled on existing installations.

The one-time exchange accepts `cookie: true`. It then returns an HttpOnly, SameSite=Strict, Path=/ cookie with a one-hour maximum age, without returning the session token in JSON. The server stores only its digest. POST `/api/ui-login/renew` renews a live session; `/api/ui-login/revoke` invalidates it and expires the cookie. Expired sessions cannot renew. Restarting the service loses all sessions. Cookie mutation requests require the exact loopback Origin and actual listener port; forwarded requests are rejected. Cookie credentials cannot administer membership or credentials.

HTTP cookies are not scoped by port: other services on the same hostname remain a local trust boundary. HttpOnly does not protect against malicious local software or same-origin script execution. The cookie is not Secure because this entry is HTTP loopback. Do not expose the browser entry through a tunnel. Header checks do not prove that an arbitrary proxy is absent. Supported MCP routing must remain separate and does not mint browser sessions. Real OS/vendor integration is not certified by synthetic tests.

The remaining product choice is whether to add an OS-authenticated browser bootstrap or accept a documented weaker trust model for unattended homepage login. This implementation does neither silently.
