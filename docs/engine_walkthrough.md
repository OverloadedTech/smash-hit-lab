# How Smash Hit fits together

**CONFIRMED:** this APK is a custom native C++ game, using Qi engine facilities, Lua 5.2, OpenGL ES graphics and native convex-body physics. Android's GameActivity supplies the application/window lifecycle and platform integrations. It is not Unity or Unreal, and these tools do not replace its engine.

Several systems combine into what looks like one continuous world:

1. Level XML chooses rooms. Room Lua assembles a sequence of real segment sources, often with weighted random choices.
2. Each segment has readable authoring XML, a compact baked render mesh, and references to scripted objects. Static collision is built separately from the render mesh.
3. Obstacle Lua creates bodies, shapes, joints and behaviors. Native C++ updates motion, collision, breakage, balls, scoring and powerups.
4. The normal camera/progression pose moves along negative Z and is synchronized with room length and music. The class named Player mainly holds progress/profile data.
5. The loader keeps an ordered current/next room pair, with separate rules for room preparation, mesh preload, obstacle lifetime and drawing. It is not an unrestricted open-world chunk cache.
6. The renderer combines baked lighting, tile textures, glass/material passes, effects, reflections and fog. Those choices help a relatively small nearby world feel continuous and expansive.

The standard room shader starts adding fog around projected depth 5 and reaches full fog around 25. It interpolates between upper and lower colors using projected vertical position. This is a shader blend, not volumetric fog filling the whole level. Other materials/passes have their own variants. Removing fog and normal axial culling helps inspection but cannot recreate unloaded rooms or faces discarded during baking.

Physics uses bodies with convex shapes, spatial trees and native solver routines. Script joints/motion build many of the moving obstacles. Render mesh, collider, entity lifetime and visibility are separate responsibilities. That is why moving only a rendered vertex buffer is insufficient: the editor also updates real shape geometry, collision bounds and mass properties.

The glass breakage path cuts convex polyhedra at the impact region, separates disconnected groups into bodies and recomputes mass properties. Debris, particles and sound supplement those larger physical pieces. The detailed static findings and remaining uncertainties are in [glass shattering](glass_shattering.md).

Fallen projectiles have separate physics-removal and entity-destruction stages; see [ball lifecycle](ball_lifecycle.md). Reopening the app also has two different mechanisms: keeping the existing Android process alive, and reconstructing progress from a compact disk quick-save; see [resume research](quick_resume.md).

Readable content scripts and exported native symbols expose a lot of the structure, while the unusual music/progression coupling, rebasing and layered streaming reward controlled experiments. Understanding these mechanisms does not provide the complete original source, asset production pipeline or every platform integration. The remaining limits are tracked in [unknowns](unknowns.md).
