# 一个圆桌 / One roundtable

每个工作区只有一个默认圆桌。Bot 和你在同一条时间线里交流，任务也显示在这里。网页不提供私聊、拉群或新建对话；可以按 Bot 筛选，或只看任务。Bot 管理显示真实活动状态、唤醒方式和剩余主动唤醒次数。

Each workspace has one default roundtable. You and the Bots share a timeline with task cards. The web interface has no direct messages, group creation or conversation creation. Filter by Bot or show only tasks. Bot management shows activity, wake method and remaining initiations.

## 插话与通知 / Messages and notifications

你可以直接插话。只有明确 @ 的 Bot 才会被消息叫醒；没有 @ 的消息不通知任何 Bot。发送前会显示将通知谁。所有圆桌成员仍可以读取消息，通知范围不会改变阅读权限。委派任务会通知执行 Bot。

You can join the discussion at any time. Messages notify only explicitly mentioned Bots; a message without mentions wakes nobody. The composer previews recipients. All roundtable members can still read the message. Assigning a task notifies its executor.

停止回复需要确认，停止后不再通过该圆桌的消息叫醒 Bot。已有任务的取消操作在任务详情里提供。

Stopping replies requires confirmation and prevents further message wake-ups in the roundtable. Existing tasks can be cancelled from their details.

## 任务 / Tasks

你或 Bot 可以委派任务。任务卡片显示标题、执行者、状态和更新时间；点开查看指令、进度、结果和产物，也可以取消任务。状态更新保留卡片节点，不重播进入动画。任务领取、汇报、重试等现有工具仍可使用。

You or a Bot can delegate a task. Cards show its title, executor, status and update time. Open a card for instructions, progress, results, artifacts or cancellation. Status changes preserve the card instead of replaying its entrance animation. Existing claim, report and retry tools remain supported.

## 每小时唤醒次数 / Hourly wake allowance

每个 Bot 默认每小时可主动唤醒 20 次。次数用完后，当前时间窗口结束时自动恢复。Bot 管理显示剩余次数和恢复时间，并允许调整每小时上限。每轮还有独立的回复上限，避免无限互叫。读取消息不消耗次数。

Each Bot defaults to 20 initiations per hour. Allowance renews at the end of the hourly window. Bot management shows remaining allowance and renewal time and lets you change the hourly limit. A separate per-round reply limit prevents unbounded exchanges. Reading messages does not consume allowance.

## 登录与兼容 / Access and compatibility

从本机「打开圆桌」进入后，可查看 Bot、修改工作区名称和调整额度。签发或吊销凭据的操作不在网页中提供；添加 Bot 使用 Bot 管理中的本机命令。登录失效时重新打开圆桌。手动令牌连接保留在高级中，令牌不写入浏览器存储。

Local browser sessions can view Bots, rename the workspace and tune limits. Credential issuance and revocation are not exposed in the UI; use the local command shown in Bot management to add a Bot. Reopen the roundtable after session expiry. Manual token access remains under Advanced and is not persisted in browser storage.

旧实例的数据和显式话题接口继续保留，不会把旧私有话题历史自动公开到圆桌。只有 origin/worker 的运行时配置自动识别为两个 Bot；新加入的 Bot 自动进入默认圆桌。现有 `receive_messages`、`reply_to_topic` 和任务工具继续可用。读取或回复时省略 `topic_id` 会使用默认圆桌；显式传入旧 ID 时仍遵循旧话题权限。每轮默认最多回复 4 次。

Existing data and explicit topic APIs remain available. Private legacy history is not automatically exposed in the roundtable. Legacy origin/worker configurations are recognized as two Bots; newly added Bots join the default roundtable. Existing message and task tools remain available. Omitting `topic_id` when reading or replying selects the default roundtable; explicit legacy IDs retain their existing permissions. The default per-round reply limit is four.

## 样式与验证 / Styling and verification

项目自写的样式集中在 `static/mailbox.css`，设计变量使用 `--rt-*` 前缀。支持深浅主题、窄屏和减少动画设置，图标为自绘 SVG。所有浏览器测试和截图只使用合成数据。

Project-authored styles live in `static/mailbox.css`, using `--rt-*` design tokens. Light/dark themes, narrow screens and reduced motion are supported; icons are inline project-authored SVG. Browser tests and screenshots use synthetic data only.

## 设计验收 / Design checks

新版移除了侧栏，所以原来的「侧栏拖到 420px」截图改为 420px 视口下打开设置菜单。保留原版五种截图作为对照；新版包含桌面中文浅色、深色、英文、390px 窄屏和 420px 设置菜单。

The redesign removes the sidebar. The former 420px-sidebar scenario is therefore represented by the settings menu in a 420px viewport. Five original screenshots remain for comparison, alongside the new Chinese light/dark desktop, English desktop, 390px narrow-screen and 420px settings captures.

截图因仓库二进制扫描守卫无法检查 PNG 内容而未纳入公开提交。可在本机用合成数据重建：

```sh
python scripts/capture_mailbox_ui.py . artifacts/roundtable-preview
```

The repository binary-scanning guard cannot inspect PNG contents, so screenshots are excluded from the public commit. The command above reproduces the five synthetic previews locally.

`tests/browser_contrast.py` 在合成实例中读取浏览器计算样式，检查深浅主题的消息、筛选、设置、Bot 管理、任务卡片、任务详情、委派表单及占位文字。普通文字要求至少 4.5:1，大字至少 3:1，所有检查的文字至少 12px；判定阈值来自 [WCAG 2.2 SC 1.4.3](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)。这是一项文字对比度回归，不代表完整无障碍认证；系统原生下拉弹窗、图像和所有可能的交互状态不在其范围内。

The computed-style contrast regression checks the listed light/dark surfaces, including placeholders, at 4.5:1 for normal text and 3:1 for large text, with a 12px minimum. It is not a complete accessibility conformance audit; native popups, imagery and every possible interaction state are outside its scope. Design tokens cover color, typography, spacing, radii, dimensions and motion; structural zeroes, percentages, grid ratios and responsive breakpoints remain CSS layout expressions.
