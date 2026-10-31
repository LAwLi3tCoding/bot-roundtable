# Original volume study / 原创体积预览

Open `index.html` in a desktop browser. No server, network, build, dependencies, or external assets required. This isolated study does not change the application.

Original analytic ellipsoids are rotated in yaw/pitch/roll, orthographically projected with exact support-point silhouettes. Eye contours lie on their surfaces; rotated surface normals control partial tangent clipping and rear occlusion. Optional radial shading is an artistic volume cue, not physically based lighting and not a claim about any other product's default renderer. The three shapes are ellipsoids; a soft bean and state integration are deliberately deferred until the first visual gate. Shapes and eyes use independent original formulas and chosen dimensions. No vendor paths, coordinates, code, fonts or materials are included.

The page shows 128 px front/quarter/side/rear, 96 px solid versus shaded, actual 32/48 px, and live rotation. Motion stops for reduced motion, hidden document, offscreen demo, pause, and page disposal. This is a geometry/motion study, not simulated external-bot status.

Verification here: `node --test preview/test_volume.js` passes four geometry tests. Browser launch was attempted but failed before page rendering: Chromium `process_singleton_posix.cc:297 socket() failed: Operation not permitted (1)`, SIGABRT. No screenshot or clip is claimed yet. Actual browser capture and visual inspection are required before integration. Run the existing full suite again after integration; this study's focused checks are not full app acceptance.


## Independent browser evidence / 独立浏览器验证

Captured from exact preview source commit `7f2d70d1873cde78c2a41f54cb918373c17c4605` in an isolated QA directory using system Chromium via a temporary loopback HTTP server. `file://` navigation was blocked by browser policy; no policy or permissions were changed. The application/main branch was not modified or integrated.

- [Full overview / 全览](evidence/overview.png)
- [Front, quarter, side, rear / 四向](evidence/poses.png)
- [Actual 32/48 px / 实际尺寸](evidence/sizes-32-48.png)
- [10-second actual rotation / 10 秒旋转实录](evidence/rotation.webm)

Visual findings: front shows two eyes; the farther eye becomes narrower at quarter turn; side shows only one thin tangent-edge eye; rear shows no eyes. Actual browser SVG bounds corroborate this: eye widths in viewBox units are 4.5/4.5 (front), 4.381/2.795 (quarter), 1.454/0 (side), 0/0 (rear). The widths change through geometry and visibility clipping, not CSS scaling of a flat face. At 32 px the side eye is barely legible; at 48 px it remains a small edge mark. This is expected foreshortening but a real small-size readability tradeoff requiring product review.

The optional shading is fixed artistic radial shading, not physical 3D lighting. Variants are still ellipsoids, not a soft-bean mascot. No vendor assets are present and no product visual acceptance is implied.

The recording contains 100 actual screen captures at 10 fps, 1280×1080 VP9, exactly 10 seconds. Ten decoded frames from its rotation interval had ten distinct hashes; the recording is not a still image. Manual pause/resume, emulated OS reduced-motion, and offscreen pausing were tested in the real browser. Page console produced no JavaScript errors (only the local server's unused favicon 404). Four geometry tests also pass; those tests alone are not the visual evidence.

实测证明眼睛在转头时确实缩短并被曲面遮挡，背面消失；32 px 的侧眼太细，不能把数学正确直接当作小尺寸视觉验收通过。暂不整合到主应用，等待用户审图。
