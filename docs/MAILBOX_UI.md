# Mailbox chat interface

This is an independent implementation informed by Grok Bot 0.78.1's installed compiled frontend and four user-supplied desktop screenshots reviewed on 2026-11-03. The private reference images remain outside the repository. No conversation text, account identity, vendor code, icons, fonts or artwork was copied. Deliverable screenshots come from our running application with synthetic data.

## Reference and interpretation

The compiled source is `Contents/Resources/app.asar`, renderer bundles `index.eager-app-D1juOWZp.js`, `index.eager-common-DbK3Oi_r.js`, and `index-Dh7EWA8t.css`. `Xn.Root` registers `home:a0t`; `a0t` renders `i0t` from the current screen model. The root mounts `g8` with sidebar `k5e` and main container `eFn` (`Xn.Workspace`). `Bwn` constructs the screen model, including `T5t` for chat identity. `i0t` mounts the toolbar, transcript surface and `L$` input dock; `R$` anchors the composer. These are compiled symbols, not recovered original source names.

The supplied pixels corrected several earlier assumptions:

| Reference observation | Product implementation |
| --- | --- |
| Flat, saturated character silhouettes with pale eyes; no sculpted highlights | Original geometric silhouettes and flat fills replace the earlier shaded characters. Shape and eye geometry are independently drawn. |
| Centered floating identity capsule | Centered conversation identity opens details; All and task views open workspace management. A two-bot topic without the owner shows both bot identities. |
| Large pinned portraits above normal conversation rows | Explicit Pin/Unpin controls in conversation details; preferences are local and scoped to the current workspace. No bots are silently marked as pinned. |
| Direct chat omits repeated sender portraits and names; multi-party chat shows author labels and small portraits beside the bubble bottom | Direct human/bot topics use that quieter visual hierarchy. Sender names remain in accessible text. Groups retain author labels, and human messages stay right-aligned. |
| Compact account/footer controls | Connection remains directly reachable; workspace, appearance and management controls are in a keyboard-accessible disclosure. All and tasks retain visible product-specific entries. |
| Compact summaries for native events and bot exchanges | Our existing topic and task data remains authoritative. We do not fabricate native system events, rich artifact cards, voice/file actions or typing states. |

The source default sidebar is 280px, adjustable 240–400px, with an 88px compact mode. This product starts at 320px to better reflect the supplied desktop composition, then preserves the user's chosen width. Source normal/pinned avatar sizes are 36/60px; expanded conversation rows are 54px. General body typography is 14/20px. The 15/22px transcript override is feature-gated in the source and is our chosen presentation, not proof of the reference account's flag state. Bubble padding is 7px/12px, radius 18px and maximum width `min(80%,560px,100% - 82px)`. Complex consecutive-author corner grouping is not reproduced.

The dock uses a 960px maximum width with 16px minimum side and lower padding. Its compact frame is 44px high with 22px radius. Newline or a second wrapped line expands the text area to 20–120px, with 10px top and 46px lower control space and 18px radius; expansion persists until empty. Independent 300ms easing is used instead of the bundled spring curve. Timestamp boundaries follow the first-message, 15-minute and local-date rules. Individual times are available to screen readers and on hover, keyboard focus and touch; this is an accessible adaptation of native timestamp peeking.

Static images establish composition and material appearance, not animation behavior. Our blink and hover motion remain original cosmetic effects. Browser tests sample real animation progression, verify that polling does not replay message entrances, and confirm reduced-motion disables them. Exact native movement, theme variants not shown in the supplied images, advanced message grouping and native event/artifact surfaces remain unverified or deliberately outside this product's capabilities. This is not a claim of pixel identity.

## Mailbox behavior

The sidebar opens a direct topic when a bot is selected. New chat chooses one or more bots; multiple bots create a group. All shows every topic in the current owner-authorized workspace, including bot-to-bot conversations. Opening a topic does not join it. Sending from All joins the owner atomically with the message; existing topic history is visible. A bot never receives owner-wide access.

Every message is delivered to the other topic members. A normal human message requests replies from participating bots within the topic budget; an explicit @ selection narrows who is notified. Bot-origin messages use explicit wake requests. Delivery, notification and an actual provider run are separate states. Stop replies closes the topic to further messages, including human messages; create a new topic to continue. The square stop control retains an accessible label and tooltip.

Appearance offers light, dark and system modes. Avatar and pin preferences stay in browser storage and load no remote images. Names and message bodies render as text, never HTML. Drafts remain in memory while switching topics; access secrets are not persisted by these controls. Background refresh retains same-topic message focus without stealing control focus. Narrow-screen navigation retains tasks, conversation details, settings and return focus.

Task and handoff controls remain available through the sidebar task entry. This release initializes a fresh schema; it does not migrate or modify an existing deployment. Real Grok account wake-up remains a separate deployment acceptance step.

## Verification and previews

Browser checks cover direct/group/All flows, duplicate submission, refresh, cancellation, settings, pin/unpin persistence, centered identity, avatar/text separation, bot exchange identity, dark mode, reduced motion and actual animation progression. The synthetic fixture includes longer paragraphs to expose layout differences rather than relying only on one-line bubbles.

Regenerate previews with `MAILBOX_SCREENSHOTS=artifacts/mailboxes PYTHONPATH=. python tests/browser_mailboxes.py`. Binary deliverables are distributed through Library because the repository upload guard blocks unscannable image files. Original user screenshots are never included in the public branch or PR.
