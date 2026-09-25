#pragma once
#include "state.hpp"

namespace shdev {
// Play owns player movement. Editing owns a separate, paused inspection view.
struct PlayControls {
    bool active = false, editing = false, exploring = false, tools = false, automatic = true, startPending = false;
    bool rails = true, stopped = false, backward = false;
    bool playFog = true, editFog = false, savedEdits = true;
    bool customFov = false;
    float moveSpeed = 6, travelSpeed = 1, lookSpeed = 1, lens = 60;
    bool turning = false;
    Vec3 turnTarget, resumeEuler;
    bool haveResumeView = false;
    double movementSeconds = 0, turnSeconds = 0;
    uint64_t movementUpdates = 0;
    uint64_t shotSpawns = 0;
    Json lastShot;
    Vec3 moved;
    std::string settingsError;
    void load();
    void saveSettings();
    bool command(const Json &c);
    void enter();
    void pause(bool edit);
    void leaveLegacy();
    void levelStarted();
    void frame(float dt);
    void prepareUpdate();
    void configureTravel();
    bool fogHidden() const;
    Json info() const;
};
extern PlayControls play;
}
