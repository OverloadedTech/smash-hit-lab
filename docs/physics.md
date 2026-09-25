# Physics and collision

**CONFIRMED (symbols and disassembly):** native physics uses `Body`, `Shape`, `Physics`, `Polyhedron`, `TdSolver`/`td*` routines, broadphase trees (`QiDbvt3`), and convex GJK/EPA/MPR support. There is no evidence that this APK's gameplay collision is Unity PhysX or Unreal physics. Exact upstream provenance of all solver code remains UNKNOWN.

Rooms create a native static body. Every source XML box produces a `Shape` using half extents and a translation baked into its polyhedron. Static rendering is a separate baked mesh. Script obstacles create boxes, convex meshes, joints and motion constraints through `mg*` Lua bindings. Bodies carry transforms, center-of-mass transforms, linear/angular velocities, mass/inertia and joint references. Shape vertices and native collision points are separate retained arrays.

`Body::setTransform` updates both the entity transform and derived center-of-mass pose, recomputes shape bounds, updates the spatial tree, and refreshes body bounds. `Body::computeMassProperties` rebuilds mass/inertia and collision-point data from shape polyhedra. `Polyhedron::computeNormals(true)` recomputes face and vertex normals. The addon calls these methods after editing geometry; changing just the rendered mesh would leave collision in the old location.

Native polyhedron vertices are 24-byte position/normal records. Directed edges store short indices, including start vertex and next edge. Faces reference an edge and a plane normal. Selection triangulates these actual convex face loops for script bodies, and tests the actual indexed baked mesh for static geometry. It does not substitute an invented object model.

Noclip camera/player-flight movement bypasses the obstruction ray. Actual-player noclip additionally suppresses normal corridor-hit penalties while that flight mode is active. With noclip disabled the addon calls native `Level::raycast(start,end,mask,...)` for each movement step. That gives point-camera obstruction behavior; it does not emulate the normal game collision response. Transform edits are limited to positive scale factors 0.01–100 to keep convex topology valid. Existing topology is preserved; arbitrary constructive solid geometry and fragmentation authoring are outside this phase.

Runtime editor tests have verified a transformed static box and a scripted scoretop glass body against the original native raycast, including geometry-checksum restoration. See `experiments.md` for recorded runs. This is not validation of every shape/material combination.

The inspected fracture pipeline cuts convex shapes, separates disconnected groups and recomputes body mass properties, with separate cosmetic debris and particles. Its static evidence and unresolved details are documented in [glass shattering](glass_shattering.md).

The stored Body AABB in this build can be narrower than its actual shape geometry: the native bound-combination routine does not union every shape maximum. The editor computes its own bounds from transformed native vertices, while retaining the native values as a separately named diagnostic field. Shape bounds/spatial-tree updates still use the original native methods. Shape +0x60 distinguishes collision-tree membership and must not be treated as a hidden-surface flag.

Projectile retirement and native entity destruction are documented separately in [ball_lifecycle.md](ball_lifecycle.md). The original-controls path retains original cleanup. First-person Play adds a scoped, bounded projectile-lifetime exception so backward and below-corridor shots can stay in the native solver; see that document for exact limits and evidence.
