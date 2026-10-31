# Actual desktop recording / 桌面实录

[avatar-motion.webm](avatar-motion.webm) is an actual 1280×900 browser screen recording: 220 captured frames, 10 fps, 22 seconds, VP9. It is not a generated animation or a still screenshot. The original application SVG/CSS supplies the motion.

Timeline (approximate): 0–1s idle; 1–9s pending Lead/peer turns; 9–14s replies received and completed conversation (including English UI); 14–18s another pending task stopped; 18–21s a synthetic failure reply; 21–22s reduced-motion preference applied.

Only local demo identities are used. `tests/record_avatar_demo.py` starts a temporary in-memory backend; real browser clicks create/stop runs, and the test driver supplies explicitly labeled synthetic replies through Store's inbox/reply protocol. It never connects to Grok, dot or DS Bot. A “working” expression means this relay is awaiting that participant's reply, not proof that an external product is currently executing.

录制的是实际浏览器像素，不是生成图。全部内容为本地合成 demo：等待、完成、停止、失败都来自实际任务状态；回执由测试脚本提交。没有外部 Bot 连接，也没有可见令牌。小头像不播放持续动效，较大头像在可见且系统未要求减少动效时播放轻微动效。

Reproduce locally after installing the normal development dependencies and system `ffmpeg`:

```sh
CHROMIUM_PATH=/usr/bin/chromium PYTHONPATH=. python tests/record_avatar_demo.py
```

The script captures frames only after authentication and closes the in-memory backend afterward. Captures include the whole desktop window and composer. Source images, fonts and code from other products are not used. Mobile and real-provider interoperability were not tested in this refinement.
