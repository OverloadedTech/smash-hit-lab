#pragma once
#include "state.hpp"
#include <set>

namespace shdev {
// Original balls and physics, with bounded lifetime in first-person play.
class ProjectileTools {
    std::set<void *> boundsToRestore;
    uint64_t keptEntities = 0, keptPhysics = 0, retired = 0;
    uintptr_t lastRetirementCaller = 0;
    bool playerBall(void *body) const;
    bool withinLimits(void *body) const;
  public:
    static constexpr float maxAge = 15, maxDistance = 100;
    static constexpr size_t maxCount = 256;
    void beforeUpdate(void (*destroy)(void *, void *));
    void afterBodyUpdate(void *body);
    void beforePhysics();
    void destroyed(void *body) { boundsToRestore.erase(body); }
    void clear() { boundsToRestore.clear(); }
    bool keepActive(void *body, uintptr_t caller);
    Json info() const;
};
extern ProjectileTools projectiles;
}
