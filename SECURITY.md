# Security

## Reporting a problem

Please report security problems privately, through GitHub's private vulnerability reporting: on this repository's **Security** tab, click **Report a vulnerability**. Don't open a public issue or pull request for them.

Say what an attacker could do, what they need to start with (another local user? a web page you visit?) and how to reproduce it. Use made-up session names and paths.

Only the latest `main` is supported. Problems in Claude Code itself belong with Anthropic, not here.

## What the tool does with your data

`cc-session-restore` reads Claude Code's own files under `~/.claude` (or `CLAUDE_CONFIG_DIR`). It doesn't change them and doesn't send anything over the network. To reopen a session, it runs `claude --resume <session-id>` in a new terminal tab, for session ids it found in those files.

## The `--gui` page

`--gui` (and the **Claude Code sessions** launcher) runs a small web server so your browser can show the picker. Here's how it's protected:

- **Loopback only.** It listens on `127.0.0.1`, on a random free port unless you pass `--port`.
- **One-time link.** The URL carries a random token. The first page load with that token gets a random cookie (`HttpOnly`, `SameSite=Strict`) and uses up the token. Loading the link again gets a 403.
- **Cookie required.** Every API call needs the cookie. Without it, the server answers 403.
- **Host check.** Requests whose `Host` header isn't `127.0.0.1:<port>` or `localhost:<port>` get a 403. This blocks DNS rebinding, where a web page's own domain is pointed at your machine.
- **Only your sessions, only once.** The open request carries session ids only. The server looks each one up in Claude Code's files and ignores ids it doesn't know or that are already running, so a request can't make it run any other command. A lock allows one open per picker: a second request gets a 409, unless the first one failed with an error.
- **Short-lived.** The server stops after it opens sessions, or after 15 minutes with no authorized requests.
- **Titles shown as text.** Session titles can come from model-written text. The page inserts them as plain text, not HTML.

### Limits

- **Whoever loads the link first wins.** The URL is printed in the terminal and passed to the browser on its command line, where other users on the same machine may be able to see it in the process list. If another program loads it before your browser, it gets the cookie and your browser gets "This link has already been used".
- **It doesn't protect you from programs running as you.** They can read `~/.claude` directly, or take the cookie from your browser profile.
- **Cookies aren't separated by port.** While the picker runs, your browser also sends the cookie to any other server on `127.0.0.1` that it visits. Browsers treat other ports on the same host as the same site, so `SameSite=Strict` doesn't stop a page served from another local port either. The server doesn't check `Origin` or `Content-Type`. So a hostile web server on your own machine, visited in that browser while the picker runs, could list your sessions (titles, folders and ids) and open them once.
- **Plain HTTP.** Traffic stays on the loopback interface and isn't encrypted. The cookie isn't marked `Secure`.
- **No user check.** Any local user can connect to the port. The token and cookie are the only barrier.

At worst, someone who gets past all this can see your session list and reopen your own sessions in new terminal tabs. They can't run other commands through the page.
