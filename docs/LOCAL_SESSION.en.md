# Restricted local browser sessions

Opening an unauthenticated HTTP homepage does not issue a session. A loopback socket peer and matching Host/Origin cannot distinguish a browser from an arbitrary transparent local proxy. The safe default therefore retains the credential-backed `local_runtime.py ui` launch and manual token fallback. No new setting is enabled on existing installations.

The one-time exchange accepts `cookie: true`. It then returns an HttpOnly, SameSite=Strict, Path=/ cookie with a one-hour maximum age, without returning the session token in JSON. The server stores only its digest. POST `/api/ui-login/renew` renews a live session; `/api/ui-login/revoke` invalidates it and expires the cookie. Expired sessions cannot renew. Restarting the service loses all sessions. Cookie mutation requests require the exact loopback Origin and actual listener port; forwarded requests are rejected. Cookie credentials cannot administer membership or credentials.

HTTP cookies are not scoped by port: other services on the same hostname remain a local trust boundary. HttpOnly does not protect against malicious local software or same-origin script execution. The cookie is not Secure because this entry is HTTP loopback. Do not expose the browser entry through a tunnel. Header checks do not prove that an arbitrary proxy is absent. Supported MCP routing must remain separate and does not mint browser sessions. Real OS/vendor integration is not certified by synthetic tests.

The remaining product choice is whether to add an OS-authenticated browser bootstrap or accept a documented weaker trust model for unattended homepage login. This implementation does neither silently.

## Click “Open Roundtable” on macOS

An installation maintainer can generate a clickable app once, from the installation directory:

```sh
.venv/bin/python scripts/local_runtime.py create-ui-launcher --output '<EXISTING_OUTPUT_DIRECTORY>/Open Roundtable.app' --state-dir '<STATE_DIRECTORY>' --name default
```

Replace the placeholders with your installation paths; quote paths containing spaces. Use the configured instance name. The command creates a new app and refuses to overwrite an existing one. It does not read credentials, start services, install into Applications, or change authentication settings. Put the generated app somewhere convenient or add it to the Dock yourself. Daily use is simply double-clicking it: the existing `ui` flow authenticates and opens the browser automatically. You never need to see or enter the one-time code. If the service is not running, a click first starts it the way `up` does (reusing the instance's saved proxy and sleep-prevention settings, and starting the tunnel when a runtime key exists), then opens the page once it is ready. Repeated clicks during startup wait for the first start instead of starting twice. If startup fails or times out, a system alert shows the reason code and the log directory. Recreate the shortcut if the checkout or Python path moved.

The app stores paths, arguments and the generating shell's `PATH` (Finder's default `PATH` cannot find `tunnel-client`), never a token or code. Each click appends its JSON result, which contains no token or code, to `logs/ui-launcher.log` in the instance directory. Apps generated before this change do not start the service; rename the old app as a backup and generate a new one. Tests execute the generated shell launcher with synthetic paths, including spaces and shell metacharacters. Finder/LaunchServices and macOS application-security prompts have not been tested natively. On Linux, a desktop launcher may invoke the equivalent `local_runtime.py ui --state-dir ... --name ...` command with terminal display disabled; this generator currently emits only macOS apps. The Windows managed UI flow remains unsupported.

A session lasts one hour after exchange or successful renewal. The open page attempts renewal every five minutes; an expired session or server restart requires clicking the app again. It is neither a code prompt on every visit nor permanent authentication.

Direct URL research: an already authenticated cookie can restore a visit safely. A new anonymous HTTP request cannot prove local-user presence from socket/Host/Origin alone. A future signed OS launcher or browser-extension/native-messaging bridge could obtain a short-lived capability through an OS-authenticated channel and open the browser. This requires a trusted installed component and explicit installation approval, not relaxed HTTP checks. Arbitrary transparent forwarding of the browser entry remains outside the guarantee.
