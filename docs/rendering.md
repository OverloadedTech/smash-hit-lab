# Rendering

**CONFIRMED (static analysis):** EGL creates an OpenGL ES context and the game uses GLES 2 style shaders/buffers through `QiRenderer`. Android supplies a `GameActivity` surface; this APK does not contain a Unity/Unreal renderer. The high-level native chain is `Game::frame → Game::update / Game::draw → Level::draw → RenderLevel::draw`.

`Display` holds the main 3D viewport and additional GUI/render-target viewports. `QiViewport` stores position, an XYZW quaternion, projection and model-view matrices. `setMode3D` takes a horizontal field of view in degrees, near and far planes. The native calculation divides the horizontal tangent extent by aspect ratio to obtain the vertical extent. The normal path uses near/far values 0.2 and 100 in the inspected setup; developer mode supplies 0.05 and 2000 to inspect retained geometry at larger distances.

Room static geometry is loaded into `RenderBatch` vertex/index buffers. `Room::draw` supplies the static room body's transform, then rejects batches using their axial Z bounds. Normal rendering thus assumes a forward path even though its viewport supports a general quaternion. Dynamic body meshes are assembled from actual polyhedra by `RenderLevel::fillBuffers*`; some work runs through `JobManager` and is joined before drawing completes. Their face selection also uses the normal level camera position.

The developer camera temporarily supplies its pose to the main viewport and render-time camera consumers during `Game::draw`, then restores them before returning. Developer room drawing submits every retained loaded batch through the original renderer. No simulation update uses the temporary pose. Rendering an unloaded room is impossible without explicitly rebuilding it; extending the far plane cannot create missing content.

37 bundled GLSL sources contain shared vertex/fragment variants selected by defines. Native rendering includes opaque/static geometry, glass and other shape material types, decals, particles/debris, fog, background and reflection passes. Baking removes some hidden/internal static faces. Moving a source box therefore does not reconstruct missing faces or recalculate original baked lighting/UVs. Reflection masks and decals are separate geometry and are not automatically reauthored by the box editor.

Texture containers and baked mesh records are documented in `level_format.md` and `apk_structure.md`. `analysis/reports/shaders.json` and `textures.json` inventory the actual assets. **UNKNOWN:** complete semantics of every shader/material flag and correctness of every original reflection effect for arbitrary camera poses. These are explicit limits of this phase's tooling, not evidence of a general reconstructed renderer.

## Inspection rendering

The shipped static shader uses `clamp(0.05 * (gl_Position.z - 5.0), 0.0, 1.0)`: fog reaches its full value at projected depth 25. This is a projection-dependent depth value, not spherical distance from the camera. Extending the camera far plane alone did not reveal distant retained geometry. The addon augments that exact fog expression at shader compilation with an inspection uniform, then selects it from separate Play and Tools/Edit preferences. It also optionally suppresses `GL_CULL_FACE` during that draw. Program-link events invalidate cached uniform locations. Both options use the original shaders/materials and retain original shader behavior when the corresponding fog preference is enabled; packaged shader bytes remain unchanged.

These options reveal retained surfaces when flying outside the corridor. They cannot recreate faces removed by the original baking process. Original game HUD rendering is suppressed during inspection/editing, leaving the Android tools and world visible. First-person Play retains the original HUD and shooting input.

Telemetry collected inside a render callback must distinguish the temporarily substituted camera pose from progression. The addon captures the normal pose before the draw override and uses it for player-position fields and normal axial-visibility labels in load events; camera fields are recorded separately.
