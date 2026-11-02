# Mailbox chat interface

The desktop layout is independently implemented from read-only inspection of Grok Bot 0.78.1's installed compiled frontend on 2026-11-02. The source is `Contents/Resources/app.asar`, renderer bundles `index.eager-app-D1juOWZp.js`, `index.eager-common-DbK3Oi_r.js`, and `index-Dh7EWA8t.css`. No proprietary code, styles, icons, fonts or artwork were copied into this repository. Native-window comparison remains pending because the Mac was locked; this is not a claim of pixel identity.

Confirmed measurements: sidebar 280px default, adjustable 240–400px, compact 88px; neutral light and dark pane/chrome/sidebar surfaces; header button sizes 36/32px; general body 14/20px. The transcript-specific style can override body with 15/22px under a feature flag (our chosen presentation), 7px vertical and 12px horizontal padding, 18px radius, and maximum width `min(80%,560px,100% - 82px)`. User messages align to the end. Agent bubble fill mixes primary ink at 6% in light mode and 4% in dark; user fill uses 100% and 18%, respectively, against chrome. Continuation corners in the reference shrink to 6px; this implementation retains separate messages with full corners. Time boundaries follow the confirmed first-message, 15-minute and local-date rules. Native toolbar placement and live avatar behavior remain unverified. Tasks remain available in the sidebar.

The app-specific composer uses a 44px compact frame with 22px radius; newline or a second wrapped line expands it to a 20–120px text field, with 10px top and 46px lower control space, and 18px radius. Expansion persists until the draft is empty; draft switches remeasure independently. The frame has a 0.5px border and elevated fill. Independent easing uses 300ms for height/radius, rather than copying the bundled spring curve. File/voice controls from the reference are not added to this product.

Time boundaries use a 28px row with 6px vertical padding and 14px/8px outer spacing, and semantic `time` elements and localized today/yesterday/date labels. Individual message times remain available to screen readers and appear on keyboard focus, hover, and touch devices. This is an accessible adaptation of the reference's timestamp-peek behavior, not a reproduction of its native gesture. Consecutive-author bubble grouping, native title islands and reference avatar motion are still pending sufficient component evidence; our character blink remains cosmetic.

The sidebar can be compacted with its menu button, or resized with its separator by dragging or using arrow keys (Home/End choose the limits). Compact rows retain accessible names and tooltips.

The sidebar opens a direct topic when a bot is selected. New chat chooses one or more bots; multiple bots create a group. All shows every topic in the current owner-authorized workspace, including bot-to-bot conversations. Opening a topic does not join it. Sending from All joins the owner atomically with the message; existing topic history is visible. A bot never receives owner-wide access.

Every message is delivered to the other topic members. A normal human message requests replies from the participating bots within the topic budget; an explicit @ selection narrows who is notified. Bot-origin messages use explicit wake requests. Delivery, notification and an actual provider run are separate states. The interface never invents typing activity. Stop replies closes the topic to further messages, including human messages; create a new topic to continue.

Appearance offers light, dark and system modes. Avatars use original shaded geometric characters and a small color palette, with an initials option; Conversation details lets the owner customize them locally. These preferences remain in browser storage and load no remote images. Message bodies and names render as text, never HTML. Drafts remain in memory while switching topics; access secrets are not persisted by these controls. Reduced-motion disables entrance, hover and blink animations. Blinking is cosmetic, never a claim that a bot is thinking. New messages animate once; polling existing messages does not restart their entrance.

Task and handoff controls remain available through the sidebar task entry. Workspace management is in the collapsible Workspace list. This release initializes a fresh schema; it does not migrate or modify an existing deployment.

## Visual verification

Earlier Library screenshots predate the installed-client revision. The four previous screenshots (`mailbox-*.png`) are captured from the actual running interface with synthetic bot names and messages. They are not design mockups. Browser checks cover direct/group/All flows, duplicate submission, refresh using the existing cookie session, cancellation, dark mode and reduced motion. Real Grok account wake-up is a separate deployment acceptance step.

Regenerate screenshots with `MAILBOX_SCREENSHOTS=artifacts/mailboxes PYTHONPATH=. python tests/browser_mailboxes.py`. Binary deliverables are distributed separately because the repository upload guard blocks unscannable image files.

## Whole-screen composition audit

A second audit followed mounted components rather than treating shared style tokens as an active screen. In the app bundle, `Xn.Root` registers `home:a0t`; `a0t` renders `i0t` from the current screen model. The root mounts `g8` with `k5e` as its sidebar and `eFn` as the main chat container (`Xn.Workspace`). `Bwn` constructs the screen model, including `T5t` for the chat identity. `i0t` mounts the floating toolbar, transcript surface and `L$` input dock; `R$` anchors the composer. These are compiled component symbols, not recovered original source names.

| Area | Evidence in mounted path | Independent implementation / limit |
| --- | --- | --- |
| Sidebar | `k5e` → `J4e` toolbar, `a5e` roster and `a4e` footer; `v5e` selects expanded/pinned/collapsed `cS` rows. Expanded rows are 54px tall, padded 8px. | A compact toolbar precedes the roster. Search opens on demand. Workspace and connection controls live at the bottom. All and tasks remain product-specific entries. |
| Main header | `i0t` positions its toolbar absolutely at the top; `T5t` mounts the clickable identity island and optional controls. | One floating conversation identity replaces the full-width header plus second navigation strip. Its button opens conversation details; All opens workspace management. |
| Transcript | The screen model supplies the virtual transcript, with user messages aligned to the end. | Fixed the inherited reverse-row/end-justification conflict that put human messages on the left. Sender names stay explicit for mailbox attribution. |
| Input dock | `L$` uses 16px minimum side padding, widening to center a 960px dock, and 16px lower padding. | The composer uses that geometry. The transcript shares its alignment as a product decision; this is not evidence that every native row uses the same width. |
| States | Pinned roster, group capabilities, bot tint, prose size, thread split and related views have state/feature conditions. | No account settings were inspected. We do not assert the user's active combination. No fake pinned items or native window controls were added. |

Corrections to earlier claims: the 15px transcript override is gated by `sand_chat_prose_15px`; finding its CSS does not establish that it is enabled. The 850px centered composer and two-row workspace header were our own layout, not the mounted desktop composition. The previous screenshot also exposed incorrect human-message alignment. These have been addressed at the page level; passing functional tests alone is not visual acceptance.

The original character art remains an approximation. Native materials, avatar expressions in motion, consecutive-author grouping, title-island variants and account-dependent pinned layout still require further evidence or a privacy-safe reference screenshot. No native-window match is claimed. Before/after previews use identical synthetic conversation scenarios from the running web app, not screenshots of the vendor app.
