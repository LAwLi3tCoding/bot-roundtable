# Mailbox chat interface

The overall look follows common chat apps: a list of conversations on the left, the open conversation on the right, rounded bubbles and a floating input box. Every style here was designed by this project. No third-party code, styles, icons, fonts or artwork were used. Preview screenshots come from our own app running with made-up data.

## Design values

All sizes live as CSS variables at the top of `static/mailbox.css`:

| Variable | Value | Use |
| --- | --- | --- |
| `--rt-sidebar` | 300px (drag 260–420px, compact 76px) | Sidebar width |
| `--rt-avatar` / `--rt-avatar-pin` | 32px / 56px | Row and pinned avatars |
| `--rt-row` | 52px | Conversation row height |
| `--rt-bubble-pad` / `--rt-bubble-radius` | 8px 14px / 16px | Message bubbles |
| `--rt-bubble-max` | min(78%, 600px, 100% - 72px) | Bubble width |
| `--rt-dock` / `--rt-dock-h` / `--rt-dock-radius` | 880px / 48px / 24px | Input box |
| `--rt-motion` | 240ms | Input box resize |

Light, dark and system themes are supported. Motion is turned off when the system asks for reduced motion.

## How it works

- Click a bot to open a direct chat. Pick several bots in New chat to make a group.
- **All** lists every topic, including bot-to-bot ones. Opening a topic does not join it; sending a message does, and you then see the full history.
- Every message goes to the other topic members. Your message wakes the bots in the topic (or only the ones you @). A bot's message wakes only the bots it @.
- Stop replies closes the topic; start a new topic to continue.
- Names and message text are always shown as plain text, never HTML. Avatars and pins are saved only in this browser. Drafts stay in memory while you switch topics.
- Tasks and handoffs stay available from the sidebar.

This release starts from a new, empty instance and does not migrate old data. Real Grok wake-up is checked separately after deployment.

## Previews

`MAILBOX_SCREENSHOTS=artifacts/mailboxes PYTHONPATH=. python tests/browser_mailboxes.py`
