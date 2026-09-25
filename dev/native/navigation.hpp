#pragma once
#include "state.hpp"

namespace shdev {
// Travel uses original RoomDefs and native resets. It is not a time rewind.
struct Navigation {
    bool followView = false, travel = false, fovOverride = false, unlocked = false;
    bool loading = false, rebuilding = false;
    int direction = 1, cleanupDirection = 1, pendingCheckpoint = -1;
    bool pendingEnd = false, pendingReverse = false;
    float multiplier = 1, forwardSpeed = 0;
    double travelSeconds = 0, travelWorldZ = 0;
    uint64_t travelUpdates = 0;
    float lastTravelDt = 0;
    std::string lastError;
    Vec3 viewOffset;
    float drawFov = 0, drawProjectionX = 0, drawProjectionY = 0, inputFov = 0;
    uint64_t drawFrame = 0;
    uint64_t roomRebuilds = 0, restoredDefinitions = 0;
    Json catalog;
    void load();
    bool command(const Json &c);
    Json info();
    void leaveControlMode();
    void startBeginning();
    void startFinished();
    void prepareUpdate();
    void finishUpdate();
    bool waitingForGeometry();
    void syncCamera();
    void recordProjection(void *viewport);
    void restorePassedObjects();
    void resetRoom(int index, bool atEnd, bool continuousReverse = false, float overflow = 0);
    void jumpCheckpoint(int index, bool atEnd);
    int currentCheckpoint() const;
    int checkpointCount() const;
    int checkpointForLevelEntry(int entry) const;
    bool available(int index) const;
    bool reversing() const { return state.enabled && travel && cleanupDirection < 0; }
};
extern Navigation navigation;
} // namespace shdev
