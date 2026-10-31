# Original volume study / 原创体积预览

Open `index.html` in a desktop browser. No server, network, build, dependencies, or external assets required. This isolated study does not change the application.

Original analytic ellipsoids are rotated in yaw/pitch/roll, orthographically projected with exact support-point silhouettes. Eye contours lie on their surfaces; rotated surface normals control partial tangent clipping and rear occlusion. Optional radial shading is an artistic volume cue, not physically based lighting and not a claim about any other product's default renderer. The three shapes are ellipsoids; a soft bean and state integration are deliberately deferred until the first visual gate. Shapes and eyes use independent original formulas and chosen dimensions. No vendor paths, coordinates, code, fonts or materials are included.

The page shows 128 px front/quarter/side/rear, 96 px solid versus shaded, actual 32/48 px, and live rotation. Motion stops for reduced motion, hidden document, offscreen demo, pause, and page disposal. This is a geometry/motion study, not simulated external-bot status.

Verification here: `node --test preview/test_volume.js` passes four geometry tests. Browser launch was attempted but failed before page rendering: Chromium `process_singleton_posix.cc:297 socket() failed: Operation not permitted (1)`, SIGABRT. No screenshot or clip is claimed yet. Actual browser capture and visual inspection are required before integration. Run the existing full suite again after integration; this study's focused checks are not full app acceptance.
