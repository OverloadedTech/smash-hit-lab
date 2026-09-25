#include "projectiles.hpp"
#include "play.hpp"
#include <algorithm>

namespace shdev {
ProjectileTools projectiles;
namespace {
// Return addresses of the inspected Physics::update retirement call, guarded
// by Engine's exact original-library build IDs. Other remove calls, including
// destruction, breakage and explosions, keep their original behavior.
#if defined(__x86_64__)
constexpr uintptr_t retirementReturn = 0x289517;
#elif defined(__aarch64__)
constexpr uintptr_t retirementReturn = 0x266020;
#else
constexpr uintptr_t retirementReturn = 0;
#endif
}
bool ProjectileTools::playerBall(void *body) const {
    return count(body, off::entityType) == 0 && read<uint8_t>(body, 0x56) &&
           !ptr(body, off::entityObstacle);
}
bool ProjectileTools::withinLimits(void *body) const {
    Vec3 delta = read<Vec3>(body, off::entityTransform) - read<Vec3>(engine.level(), off::levelPosition);
    float age = read<float>(body, 0xd0);
    return delta.finite() && std::isfinite(age) && age < maxAge && delta.length() < maxDistance;
}
void ProjectileTools::beforeUpdate(void (*destroy)(void *, void *)) {
    beforePhysics(); // Also restores a guard left by an interrupted update.
    if (!play.active) return;
    auto bodies = array(engine.level(), off::levelBodies);
    std::vector<void *> retained;
    auto retire = [&](void *body, const char *reason) {
        event("play_ball_retired", {{"id", state.id(body)}, {"reason", reason},
              {"age", read<float>(body, 0xd0)}, {"position", jvec(state.world(read<Vec3>(body, off::entityTransform)))}});
        ++retired;
        destroy(engine.level(), body);
    };
    for (void *body : bodies) {
        if (!playerBall(body)) continue;
        if (!withinLimits(body)) retire(body, "age or distance limit");
        else if (!read<uint8_t>(body, 0x15c)) retire(body, "inactive projectile");
        else retained.push_back(body);
    }
    if (retained.size() > maxCount) {
        std::sort(retained.begin(), retained.end(), [](void *a, void *b) {
            return read<float>(a, 0xd0) > read<float>(b, 0xd0);
        });
        for (size_t i = 0; i < retained.size() - maxCount; ++i) retire(retained[i], "projectile count limit");
    }
}
void ProjectileTools::afterBodyUpdate(void *body) {
    if (!play.active || !playerBall(body) || !withinLimits(body)) return;
    float playerZ = read<Vec3>(engine.level(), off::levelPosition).z;
    if (read<float>(body, off::entityBounds + 8) > playerZ) {
        // Level::update tests this entity-only bound immediately after its
        // virtual update callback. Shape bounds and the collision tree stay
        // untouched; restore the real body bound before physics starts.
        write(body, off::entityBounds + 8, playerZ);
        boundsToRestore.insert(body); ++keptEntities;
    }
}
void ProjectileTools::beforePhysics() {
    for (void *body : boundsToRestore) engine.bodyBounds(body);
    boundsToRestore.clear();
}
bool ProjectileTools::keepActive(void *body, uintptr_t caller) {
    if (!play.active || caller != engine.base + retirementReturn || !playerBall(body) || !withinLimits(body)) return false;
    // Only this call site has just cleared the active flag for forward-path
    // or below-world culling. Keep the already registered original body in
    // the solver; its normal contacts, breakage and velocity remain native.
    write<uint8_t>(body, 0x15c, 1);
    lastRetirementCaller = caller - engine.base;
    ++keptPhysics;
    return true;
}
Json ProjectileTools::info() const {
    return {{"enabled", play.active}, {"max_age_seconds", maxAge}, {"max_distance", maxDistance},
            {"max_balls", maxCount}, {"entity_culls_avoided", keptEntities},
            {"physics_culls_avoided", keptPhysics}, {"retired", retired},
            {"bounds_pending_restore", boundsToRestore.size()},
            {"last_retirement_caller_offset", lastRetirementCaller}};
}
}
