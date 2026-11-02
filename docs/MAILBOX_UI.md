# Mailbox chat interface

The desktop layout is an independent implementation informed by the public product preview on [Grok Bot](https://x.ai/bot) and the official [message and collaborate guide](https://docs.x.ai/grok-bot/chat-and-collaboration), reviewed on 2026-11-02. The public preview shows a neutral sidebar, circular member identities and a rounded bottom composer. No proprietary code, styles, icons, fonts or images were copied. This is a reference-informed interface, not a claim of pixel identity with every version of the native application.

The sidebar opens a direct topic when a bot is selected. New chat chooses one or more bots; multiple bots create a group. All shows every topic in the current owner-authorized workspace, including bot-to-bot conversations. Opening a topic does not join it. Sending from All joins the owner atomically with the message; existing topic history is visible. A bot never receives owner-wide access.

Every message is delivered to the other topic members. A normal human message requests replies from the participating bots within the topic budget; an explicit @ selection narrows who is notified. Bot-origin messages use explicit wake requests. Delivery, notification and an actual provider run are separate states. The interface never invents typing activity. Stop replies closes the topic to further messages, including human messages; create a new topic to continue.

Appearance offers light, dark and system modes. Avatars use deterministic initials and a small color palette; Conversation details lets the owner customize them locally. These preferences remain in browser storage and load no remote images. Message bodies and names render as text, never HTML. Drafts remain in memory while switching topics; access secrets are not persisted by these controls. Reduced-motion disables the entrance and control transitions.

Task and handoff controls remain available in their existing workspace tab. Workspace management is in the collapsible Workspace list. This release initializes a fresh schema; it does not migrate or modify an existing deployment.

## Visual verification

The four delivered Library screenshots (`mailbox-*.png`) are captured from the actual running interface with synthetic bot names and messages. They are not design mockups. Browser checks cover direct/group/All flows, duplicate submission, refresh using the existing cookie session, cancellation, dark mode and reduced motion. Real Grok account wake-up is a separate deployment acceptance step.

Regenerate screenshots with `MAILBOX_SCREENSHOTS=artifacts/mailboxes PYTHONPATH=. python tests/browser_mailboxes.py`. Binary deliverables are distributed separately because the repository upload guard blocks unscannable image files.
