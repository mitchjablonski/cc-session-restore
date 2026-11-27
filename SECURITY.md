# Security

## Reporting a vulnerability

Please report security issues privately, not in a public issue or pull request.

Use GitHub's private reporting: on the repository's **Security** tab, choose **Report a vulnerability** ([direct link](https://github.com/mitchjablonski/cc-session-restore/security/advisories/new)). If that option isn't available, open an issue that only asks for a private contact, without any details of the problem.

Please include the platform, terminal and Python version, what an attacker can do, and the steps to reproduce it. Leave out real session titles, folder paths and transcript contents.

There is one supported version: the latest commit on `main`.

## What the tool does

`cc-session-restore` runs as you, on your machine. It reads Claude Code's files in your config folder (`~/.claude`, or `CLAUDE_CONFIG_DIR`) and runs `claude --resume <session-id>` in a new terminal for each session you pick. It makes no network requests except to its own local page, and it never modifies Claude Code's files. `--install` writes one launcher file (see the README).

## The browser page (`--gui`)

`--gui` starts a small web server so the picker can run in your browser. It is built so that other web pages and other programs on your machine can't use it:

- **Local only.** The server listens on `127.0.0.1`, so other machines can't reach it. By default it picks a free port (`--port` sets one).
- **One-time link.** The URL it opens carries a random token. The first page load with that token gets a random session cookie (`HttpOnly`, `SameSite=Strict`), and the token stops working; loading the link again shows "This link has already been used". Tokens are compared in constant time.
- **Cookie required.** Listing sessions (`/api/sessions`) and opening them (`/api/open`) need that cookie. Requests without it get `403`.
- **Host check.** Every request must have a `Host` header of `127.0.0.1:<port>` or `localhost:<port>`, or it gets `403`. This blocks DNS rebinding, where a web page uses its own domain name to reach a local server.
- **Opens only your sessions, once.** The page can only open sessions the tool itself found in your config folder that aren't already running; any other id is ignored. Each page opens sessions at most once.
- **Short-lived.** The server stops after sessions are opened, or after 15 minutes without an authorized request.

### Known limits

- The one-time token is on the browser's command line for a moment, where other programs running as you, or other users of the same machine, may be able to see it. Whoever loads the link first gets the cookie, and your own browser then shows "This link has already been used". Anyone who could do that could only list your recent sessions (titles and folders) and reopen them with your normal `claude` command. If you see that message without having opened the link yourself, please tell us.
- Anyone who can already change your environment variables (such as `CC_SESSION_RESTORE_CLAUDE_BIN` or `CC_SESSION_RESTORE_CLAUDE_ARGS`) or the files in your Claude config folder can already run commands as you. Those are not treated as security boundaries.
