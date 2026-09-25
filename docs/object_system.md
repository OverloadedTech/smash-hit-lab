# Object system

**CONFIRMED:** `Level` owns native entity/body collections. The exported `Entity` interface contains a type, owning Level pointer, optional Obstacle pointer, transform, and bounds. Its derived types include Body, Powerup and Water. Script obstacles own groups of entities, their transform, lifecycle flags and a `LevelScript`. A room owns its root script obstacle, obstacle definitions/live instances, a static body, render batches and additional decal/reflection geometry.

There is no recovered universal name/mesh/material/scale component schema. Many objects are compound native bodies built by Lua and have no separate mesh asset. The UI displays actual source paths, source XML child indices, native pointers, native material data and derived bounds where available. Numeric session IDs are explicitly addon-generated tracking IDs; they are not claimed to be original serialized object identifiers.

Relevant verified 64-bit layouts:

| Object | Field | Offset |
|---|---|---:|
| Entity | owning Level | 0x08 |
| Entity | type enum | 0x10 |
| Entity | owning Obstacle | 0x18 |
| Entity | position + XYZW quaternion | 0x20 |
| Entity | world AABB minimum / maximum | 0x3c / 0x48 |
| Body | shapes QiArray | 0x110 |
| Body | joints QiArray | 0x160 |
| Shape | Body pointer | 0x00 |
| Shape | material | 0x138 |
| Shape | Polyhedron | 0x178 |
| Obstacle | owning Room | 0x00 |
| Obstacle | entity collection | 0x28 |
| Obstacle | LevelScript pointer | 0x160 |

These offsets are guarded by GNU build ID in the addon and must not be reused for another APK version. `QiArray` stores count/capacity followed by a data pointer. Some arrays have inline storage. `QiString` has a heap-pointer-or-inline representation; decompilers can misidentify its hidden return arguments, so declarations were checked against callers and machine instructions.

Static room boxes are collision shapes within a shared room body, not independent transform-bearing entities. Moving a box updates its own mapped baked faces and its polyhedron. Moving a script Body uses native `Body::setTransform`; Lua, constraints or physics can move it again when simulation resumes. Edits are invalidated when the corresponding native instance is destroyed.
