#include "editor.hpp"
#include "navigation.hpp"
#include "play.hpp"
#include "projectiles.hpp"
#include "diagnostic_log.hpp"
#include <GLES2/gl2.h>
#include <android/log.h>
#include <fstream>
#include <set>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>

namespace shdev {
State state;
namespace {
DiagnosticLog diagnosticLog;
std::map<void *, std::string> obstacleNames;
std::chrono::steady_clock::time_point previousFrame = std::chrono::steady_clock::now();
double lastPublish = -10, lastSample = -10;
bool needPublish = true;
Vec3 normalPosition(void *level) {
    return state.renderOverride && level == engine.level() ? state.renderNormalPosition
                                                           : read<Vec3>(level, off::levelPosition);
}
thread_local void *updatingLevel = nullptr;
thread_local bool permittingWorldUpdate = false;
thread_local bool skippedWorldUpdate = false;
thread_local int tickAfterUpdate = 0;
thread_local bool playShooting = false;
void entityDestroyHook(void *level, void *entity);
bool practiceMode() {
    int mode = count(ptr(engine.game(), off::gamePlayer), 0x974);
    return mode >= 0 && mode <= 3;
}
void keepLastBall() {
    void *player = ptr(engine.game(), off::gamePlayer);
    if (player && practiceMode() && (state.immortal || state.unlimitedBalls)) {
        int minimum = state.unlimitedBalls ? 25 : 1;
        if (count(player, 0x8b8) < minimum)
            write(player, 0x8b8, minimum);
    }
}
void copyDisplayCamera() {
    void *display = ptr(engine.game(), off::gameDisplay);
    state.camera = read<Vec3>(display, off::displayPosition);
    state.euler = read<Quat>(display, off::displayRotation).euler();
}
void holdProgression(void *level) {
    if (!state.enabled || !state.progressionHeld)
        return;
    Vec3 target = state.local(state.heldPlayerWorld),
         before = read<Vec3>(level, off::levelPosition);
    if ((before - target).length() > .00001f) {
        ++state.progressionCorrections;
        event("rail_motion_suppressed",
              {{"native_pose", jvec(state.world(before))},
               {"held_pose", jvec(state.heldPlayerWorld)},
               {"rail_phase_seconds", read<float>(level, off::levelRailPhase)}});
    }
    write(level, off::levelPosition, target);
    write(level, off::levelRailSpeed, navigation.travel ? std::abs(navigation.forwardSpeed)
                                    : state.playerFlight ? state.flightForwardSpeed : 0.f);
    if (state.playerFlight)
        write(level, off::levelRotation, state.rotation());
}
float progressHook(const void *room) {
    // Level::update queries progress before movement and again immediately
    // after its music-driven rail movement, before all streaming predicates.
    // Only an explicit developer hold overrides that pose. Original room
    // construction, thresholds, lifetime and audio clocks remain active.
    if (updatingLevel && ptr(const_cast<void *>(room)) == updatingLevel)
        holdProgression(updatingLevel);
    return engine.roomGetProgress(room);
}
void setPlayerPosition(Vec3 local, bool held = true) {
    write(engine.level(), off::levelPosition, local);
    state.progressionHeld = held;
    state.heldPlayerWorld = state.world(local);
}
Json memory() {
    Json result;
    std::ifstream in("/proc/self/status");
    std::string key;
    while (std::getline(in, key))
        if (key.rfind("VmRSS:", 0) == 0 || key.rfind("VmSize:", 0) == 0 ||
            key.rfind("RssAnon:", 0) == 0) {
            std::istringstream s(key);
            std::string name;
            long size;
            s >> name >> size;
            result[name.substr(0, name.size() - 1) + "_KiB"] = size;
        }
    return result;
}
Json batchSnapshot(void *batch) {
    Json j;
    bool loaded = read<uint8_t>(batch, off::batchLoaded);
    void *room = ptr(batch, off::batchRoom);
    void *body = ptr(room, off::roomBody);
    Vec3 tr = read<Vec3>(body, off::entityTransform);
    float min = read<float>(batch), max = read<float>(batch, 4),
          z = normalPosition(engine.level()).z - tr.z;
    j = {{"id", state.id(batch)},
         {"path", qiString(at(batch, off::batchName))},
         {"loaded", loaded},
         {"axial_visible_normal", loaded && min < z && z < max + 25},
         {"submitted", loaded && state.freeCamera ? true : loaded && min < z && z < max + 25},
         {"offset", read<float>(batch, off::batchOffset)}};
    if (loaded) {
        j["local_z_bounds"] = {min, max};
        j["world_z_bounds"] = {min + tr.z + state.originZ, max + tr.z + state.originZ};
        j["vertices"] = count(at(batch, off::batchVbo), off::vboCount);
        j["indices"] = count(at(batch, off::batchIbo), off::iboCount);
        j["vbo"] = read<unsigned>(at(batch, off::batchVbo), off::vboId);
    }
    auto it = editor.segments.find(batch);
    if (it != editor.segments.end()) {
        j["mapped"] = it->second.mapped;
        j["boxes"] = it->second.boxes.size();
    }
    return j;
}
void centerHook(void *level) {
    Vec3 before = read<Vec3>(level, off::levelPosition);
    engine.levelCenter(level);
    Vec3 after = read<Vec3>(level, off::levelPosition);
    float shift = before.z - after.z;
    if (shift != 0) {
        state.originZ += shift;
        state.camera.z -= shift;
        event("world_rebase", {{"shift", shift},
                               {"origin_z", state.originZ},
                               {"before", jvec(before)},
                               {"after", jvec(after)}});
    }
}
void startHook(void *level) {
    navigation.startBeginning();
    Vec3 previousCamera = state.world(state.camera);
    state.progressionHeld = false;
    state.originZ = 0;
    state.savedCamera = nullptr;
    state.savedPlayer = nullptr;
    editor.clear();
    projectiles.clear();
    state.ids.clear();
    state.unloadedRooms.clear();
    obstacleNames.clear();
    event("level_start_begin");
    engine.levelStart(level);
    play.levelStarted();
    if (state.enabled && state.freeCamera) {
        state.camera = previousCamera;
    } else {
        state.camera = read<Vec3>(level, off::levelPosition);
        state.euler = read<Quat>(level, off::levelRotation).euler();
    }
    state.playerFlight = false;
    try {
        navigation.startFinished();
    } catch (const std::exception &error) {
        navigation.loading = false;
        navigation.leaveControlMode();
        state.frozen = true;
        state.error = error.what();
        navigation.lastError = error.what();
        event("navigation_error", {{"error", error.what()}});
    }
    event("level_start_end", {{"current", roomSnapshot(ptr(level, off::levelCurrent))}});
    needPublish = true;
}
void levelUpdateHook(void *level) {
    if (navigation.loading) return;
    if (play.active && read<uint8_t>(engine.game(), off::gamePaused)) { play.pause(false); return; }
    if (state.enabled && state.frozen && !permittingWorldUpdate)
        return;
    try {
        if (play.active) play.configureTravel();
        navigation.prepareUpdate();
        if (!navigation.loading) play.prepareUpdate();
    } catch (const std::exception &error) {
        navigation.leaveControlMode();
        state.frozen = true;
        state.error = error.what();
        navigation.lastError = error.what();
        event("navigation_error", {{"error", error.what()}});
        return;
    }
    if (navigation.loading) return;
    projectiles.beforeUpdate(entityDestroyHook);
    ++state.updates;
    void *previous = updatingLevel;
    updatingLevel = level;
    keepLastBall();
    holdProgression(level);
    engine.levelUpdate(level);
    updatingLevel = previous;
    navigation.finishUpdate();
}
void gameUpdateHook(void *game) {
    navigation.waitingForGeometry();
    if (state.enabled && state.frozen && state.stepRemaining <= 0 && !navigation.loading) {
        skippedWorldUpdate = true;
        return;
    }
    if (state.enabled && state.frozen && state.stepRemaining > 0 && !navigation.loading)
        --state.stepRemaining;
    bool previous = permittingWorldUpdate;
    permittingWorldUpdate = true;
    ++state.gameUpdates;
    engine.gameUpdate(game);
    tickAfterUpdate = count(game, 0x154);
    permittingWorldUpdate = previous;
    if (state.enabled && state.captureTransition) {
        float amount = read<float>(ptr(game, off::gameMenu), off::menuTransition);
        if ((state.transitionTarget == 3 && amount <= .5f) ||
            (state.transitionTarget == 1 && amount >= .5f)) {
            state.captureTransition = false;
            state.frozen = true;
            state.stepRemaining = 0;
            state.freeCamera = true;
            copyDisplayCamera();
            play.command({{"op", "workspace"}, {"value", "explore"}});
            state.message = "Transition paused · fly to inspect · Resume continues the animation";
            event("transition_captured", {{"target", state.transitionTarget}, {"amount", amount}});
        }
    }
}
void hitHook(void *level, int playerIndex) {
    if (practiceMode() &&
        (state.immortal || (state.enabled && (state.playerFlight || navigation.travel) && state.noclip))) {
        ++state.ignoredHits;
        event("damage_prevented", {{"player_index", playerIndex},
                                   {"immortal", state.immortal},
                                   {"player_noclip", (state.playerFlight || navigation.travel) && state.noclip}});
        return;
    }
    engine.levelHit(level, playerIndex);
}
void gameOverHook(void *level) {
    if (practiceMode() && state.immortal) {
        ++state.preventedGameOvers;
        keepLastBall();
        write(level, 0x2d0, 0.f);
        event("game_over_prevented");
        return;
    }
    engine.levelGameOver(level);
}
void bodyUpdateHook(void *body) {
    engine.bodyUpdate(body);
    projectiles.afterBodyUpdate(body);
}
void physicsUpdateHook(void *physics) {
    projectiles.beforePhysics();
    engine.physicsUpdate(physics);
}
__attribute__((noinline)) void physicsRemoveHook(void *physics, void *body) {
    uintptr_t caller = reinterpret_cast<uintptr_t>(__builtin_extract_return_addr(__builtin_return_address(0)));
    if (projectiles.keepActive(body, caller)) return;
    if (read<uint8_t>(body, 0x56))
        event("ball_removed_from_physics",
              {{"id", state.id(body)},
               {"position", jvec(state.world(read<Vec3>(body, off::entityTransform)))},
               {"active", bool(read<uint8_t>(body, 0x15c))},
               {"age", read<float>(body, 0xd0)}});
    engine.physicsRemoveBody(physics, body);
}
void quickSaveHook(void *player) {
    engine.playerQuickSave(player);
    event("quick_save", {{"room", count(player, 0x8b0)},
                         {"score", count(player, 0x8b4)},
                         {"balls", count(player, 0x8b8)},
                         {"streak", count(player, 0x8bc)}});
}
bool quickLoadHook(void *player) {
    bool restored = engine.playerQuickLoad(player);
    event("quick_load", {{"restored", restored},
                         {"room", count(player, 0x8b0)},
                         {"score", count(player, 0x8b4)},
                         {"balls", count(player, 0x8b8)}});
    return restored;
}
void tutorialTriggerHook(void *manager, const void *definitions, const void *player, float z) {
    // The original helper can both pause gameplay and mark a tutorial complete.
    // Suspend the entire helper while editing; never complete prompts silently.
    if (state.enabled) {
        ++state.tutorialChecksSkipped;
        return;
    }
    engine.tutorialCheckTriggers(manager, definitions, player, z);
}
void tutorialUpdateHook(void *game) {
    if (!state.enabled)
        engine.gameUpdateTutorial(game);
}
void loadNextHook(void *level) {
    event("load_next_begin",
          {{"current", roomSnapshot(ptr(level, off::levelCurrent), false)},
           {"music_location", engine.musicLocation(ptr(engine.game(), off::gameAudio))}});
    engine.levelLoadNext(level);
    event("load_next_end", {{"next", roomSnapshot(ptr(level, off::levelNext))}});
}
void sceneDrawHook(void *scene) {
    if (state.enabled && !play.active && scene == ptr(engine.game(), 0x50))
        return;
    engine.sceneDraw(scene);
}
void *classicBallHook(void *level, int playerIndex) {
    void *body = engine.levelClassicBall(level, playerIndex);
    if (body && playShooting) {
        // The original constructor adds a fixed world-axis hand offset. Rotate
        // that actual offset with the play view before the original shot sets
        // velocity, so looking backward also puts the ball in front of us.
        Vec3 origin = read<Vec3>(level, off::levelPosition);
        Transform pose = read<Transform>(body, off::entityTransform);
        pose.position = origin + state.rotation().rotate(pose.position - origin);
        engine.bodyTransform(body, &pose);
        play.lastShot = {{"id", state.id(body)}, {"position", jvec(state.world(read<Vec3>(body, off::entityTransform)))},
                         {"player_world", jvec(state.world(origin))}, {"view_rotation", jquat(state.rotation())}};
        ++play.shotSpawns;
        state.shotSerial.fetch_add(1, std::memory_order_release);
        event("play_ball_spawn", play.lastShot);
    }
    return body;
}
void inputHook(void *level, const void *input) {
    int balls = count(ptr(engine.game(), off::gamePlayer), 0x8b8);
    if (!state.enabled || (play.active && !state.frozen && !navigation.loading)) {
        void *display = ptr(engine.game(), off::gameDisplay);
        void *viewport = at(display, off::viewport);
        uint8_t savedViewport[off::viewportStateBytes];
        Transform savedDisplay{read<Vec3>(display, off::displayPosition), read<Quat>(display, off::displayRotation)};
        Quat savedPlayerRotation = read<Quat>(level, off::levelRotation);
        bool custom = navigation.fovOverride || play.active;
        if (custom) {
            memcpy(savedViewport, viewport, sizeof(savedViewport));
            engine.viewportMode(viewport, state.fov, read<float>(viewport, 0x24), read<float>(viewport, 0x28));
        }
        if (play.active) {
            // Use the same real player pose and lens for shooting as drawing.
            // Level::handleInput retains inventory, multiball and powerup logic.
            navigation.syncCamera();
            Quat rotation = state.rotation();
            write(display, off::displayPosition, state.camera);
            write(display, off::displayRotation, rotation);
            write(level, off::levelRotation, rotation);
            engine.viewportPosition(viewport, &state.camera);
            engine.viewportRotation(viewport, &rotation);
        }
        navigation.inputFov = read<float>(viewport, 0x20);
        bool previousShooting = playShooting;
        playShooting = play.active;
        engine.levelInput(level, input);
        playShooting = previousShooting;
        if (play.active) {
            write(display, off::displayPosition, savedDisplay.position);
            write(display, off::displayRotation, savedDisplay.rotation);
            write(level, off::levelRotation, savedPlayerRotation);
        }
        if (custom) memcpy(viewport, savedViewport, sizeof(savedViewport));
        if (state.unlimitedBalls && practiceMode())
            write(ptr(engine.game(), off::gamePlayer), 0x8b8,
                  std::max(balls, count(ptr(engine.game(), off::gamePlayer), 0x8b8)));
        keepLastBall();
    }
}
void entityDestroyHook(void *level, void *entity) {
    projectiles.destroyed(entity);
    event("entity_destroy",
          {{"id", state.id(entity)},
           {"type", count(entity, off::entityType)},
           {"ball", count(entity, off::entityType) == 0 && bool(read<uint8_t>(entity, 0x56))},
           {"position", jvec(state.world(read<Vec3>(entity, off::entityTransform)))}});
    editor.entityDestroyed(entity);
    engine.levelDestroy(level, entity);
    state.ids.erase(entity);
}
void roomConstructorHook(void *room, void *level, const void *name, const void *params,
                         float offset) {
    state.id(room);
    event(
        "room_construct_begin",
        {{"id", state.id(room)}, {"name", qiString(const_cast<void *>(name))}, {"offset", offset}});
    engine.roomConstructor(room, level, name, params, offset);
    event("room_construct_end", {{"room", roomSnapshot(room)}});
}
void roomDestructorHook(void *room) {
    Json j = roomSnapshot(room);
    j["state"] = "unloaded";
    j["unloaded_at"] = state.time();
    j["unloaded_update"] = state.updates;
    state.unloadedRooms.push_back(j);
    if (state.unloadedRooms.size() > 64)
        state.unloadedRooms.erase(state.unloadedRooms.begin());
    event("room_destroy_begin", {{"room", j}});
    editor.roomDestroyed(room);
    uint64_t id = state.id(room);
    engine.roomDestructor(room);
    state.ids.erase(room);
    event("room_destroy_end", {{"id", id}});
}
float segmentHook(void *room, const void *source, float offset) {
    auto shapes = array(ptr(room, off::roomBody), off::bodyShapes);
    auto batches = array(room, off::roomBatches);
    int definitions = count(room, off::roomDefs);
    float length = engine.roomCreateSegment(room, source, offset);
    try {
        editor.segmentCreated(room, qiString(const_cast<void *>(source)), offset, shapes, batches, definitions);
    } catch (const std::exception &e) {
        event("mapping_error", {{"error", e.what()}});
    }
    return length;
}
void batchLoadHook(void *batch) {
    double began = state.time();
    engine.batchLoad(batch);
    editor.batchLoaded(batch);
    event("batch_load", {{"batch", batchSnapshot(batch)},
                         {"duration_ms", 1000 * (state.time() - began)},
                         {"thread", gettid()}});
}
void *obstacleCreateHook(void *room, const void *name, const Transform *transform,
                         const void *params) {
    void *result = engine.roomCreateObstacle(room, name, transform, params);
    if (result) {
        try { editor.obstacleCreated(room, result, transform); }
        catch (const std::exception &error) { event("saved_body_registration_error", {{"error", error.what()}}); }
        obstacleNames[result] = qiString(const_cast<void *>(name));
        event("obstacle_create", {{"id", state.id(result)},
                                  {"room", state.id(room)},
                                  {"name", obstacleNames[result]},
                                  {"local_transform", jvec(transform->position)},
                                  {"entities", count(result, off::obstacleEntities)}});
    }
    return result;
}
void obstacleDestructorHook(void *obstacle) {
    auto it = obstacleNames.find(obstacle);
    std::string name = it == obstacleNames.end() ? "room/script" : it->second;
    event("obstacle_destroy", {{"id", state.id(obstacle)},
                               {"name", name},
                               {"room", state.id(ptr(obstacle))},
                               {"entities", count(obstacle, off::obstacleEntities)}});
    obstacleNames.erase(obstacle);
    engine.obstacleDestructor(obstacle);
    state.ids.erase(obstacle);
}
void obstacleUpdateHook(void *obstacle) {
    engine.obstacleUpdate(obstacle);
    if (!navigation.reversing() || navigation.rebuilding) return;
    auto entities = array(obstacle, off::obstacleEntities);
    bool expired = !entities.empty();
    float playerZ = read<Vec3>(engine.level(), off::levelPosition).z;
    for (void *entity : entities) {
        // Native forward expiry compares each entity's minimum Z. Reverse
        // expiry uses the corresponding maximum Z after the original script
        // tick. Room destruction and entity ownership remain native.
        float maxZ = read<float>(entity, off::entityBounds + 20);
        if (!std::isfinite(maxZ) || maxZ > playerZ) expired = false;
    }
    write<uint8_t>(obstacle, 0x138, expired ? 1 : 0);
}
int checkpointScoreHook(void *player, int index) {
    int score = engine.playerHighScore(player, index);
    if (navigation.unlocked && practiceMode() && count(player, 0x974) <= 2 && index > 0 &&
        index < engine.playerCheckpointCount(player)) return std::max(25, score);
    return score;
}
void checkpointLoadHook(void *player, int index) {
    engine.playerLoadCheckpoint(player, index);
    if (navigation.unlocked && practiceMode() && count(player, 0x974) <= 2 && index > 0 &&
        index < engine.playerCheckpointCount(player) && count(player, 0x8b8) < 25)
        write(player, 0x8b8, 25);
}
void roomDrawHook(void *room) {
    if (!state.renderOverride) {
        engine.roomDraw(room);
        return;
    }
    // Keep native materials, index buffers and render passes. Only the axial
    // batch rejection is bypassed, and only for a detached developer camera.
    Mat4 model = Mat4::from(read<Transform>(ptr(room, off::roomBody), off::entityTransform));
    for (void *batch : array(room, off::roomBatches))
        if (read<uint8_t>(batch, off::batchLoaded))
            engine.drawTriangles(ptr(engine.game(), off::gameRenderer), &model,
                                 at(batch, off::batchVbo), at(batch, off::batchIbo), -1, 0);
}
void drawHook(void *game) {
    bool detached = state.enabled && state.freeCamera;
    if ((!detached && !navigation.fovOverride) || !engine.level() || !ptr(game, off::gameDisplay)) {
        engine.gameDraw(game);
        return;
    }
    void *level = engine.level();
    void *display = ptr(game, off::gameDisplay);
    void *viewport = at(display, off::viewport);
    uint8_t viewportState[off::viewportStateBytes];
    memcpy(viewportState, viewport, sizeof(viewportState));
    if (!detached) {
        engine.viewportMode(viewport, state.fov, read<float>(viewport, 0x24), read<float>(viewport, 0x28));
        navigation.recordProjection(viewport);
        engine.gameDraw(game);
        memcpy(viewport, viewportState, sizeof(viewportState));
        return;
    }
    navigation.syncCamera();
    Transform normal{read<Vec3>(level, off::levelPosition), read<Quat>(level, off::levelRotation)};
    Transform camera{read<Vec3>(display, off::displayPosition),
                     read<Quat>(display, off::displayRotation)};
    Quat rot = state.rotation();
    state.renderNormalPosition = normal.position;
    state.renderOverride = true;
    GLboolean wasCull = glIsEnabled(GL_CULL_FACE);
    if (state.twoSided)
        glDisable(GL_CULL_FACE);
    write(level, off::levelPosition, state.camera);
    write(level, off::levelRotation, rot);
    write(display, off::displayPosition, state.camera);
    write(display, off::displayRotation, rot);
    engine.viewportPosition(viewport, &state.camera);
    engine.viewportRotation(viewport, &rot);
    engine.viewportMode(viewport, state.fov, .05f, state.farClip);
    navigation.recordProjection(viewport);
    engine.gameDraw(game);
    // Game draw joins its geometry jobs before returning. No simulation tick
    // sees these temporary rendering coordinates.
    write(level, off::levelPosition, normal.position);
    write(level, off::levelRotation, normal.rotation);
    write(display, off::displayPosition, camera.position);
    write(display, off::displayRotation, camera.rotation);
    memcpy(viewport, viewportState, sizeof(viewportState));
    state.renderOverride = false;
    if (wasCull)
        glEnable(GL_CULL_FACE);
    else
        glDisable(GL_CULL_FACE);
}
void enable(bool value) {
    bool leavingPlay = play.active;
    play.leaveLegacy();
    if (value && (!engine.game() || !ptr(engine.game(), off::gameDisplay)))
        throw std::runtime_error("The renderer is still starting");
    if (value && (!state.enabled || leavingPlay)) {
        void *display = ptr(engine.game(), off::gameDisplay);
        state.camera = read<Vec3>(display, off::displayPosition);
        state.euler = read<Quat>(display, off::displayRotation).euler();
        state.frozen = true;
        state.freeCamera = true;
        state.noclip = true;
        if (!navigation.fovOverride) state.fov = read<float>(at(display, off::viewport), 0x20);
        if (state.fov < 20 || state.fov > 150)
            state.fov = 80;
    }
    state.enabled = value;
    state.move = {};
    state.stepRemaining = 0;
    // A resumed saved game can already be in its original pause menu. The
    // developer freeze owns simulation stopping; clear that independent pause
    // through the original API so frame stepping is actually able to run.
    engine.gameSetPaused(engine.game(), false);
    if (!value) {
        navigation.leaveControlMode();
        state.freeCamera = false;
        state.progressionHeld = false;
        state.playerFlight = false;
        state.captureTransition = false;
        editor.clearSelection();
    }
    state.message =
        value ? "Developer mode: simulation frozen, camera detached" : "Normal gameplay restored";
    event("developer_mode", {{"enabled", value}});
}
void selectMode(const std::string &mode) {
    play.leaveLegacy();
    if (mode == "play") {
        enable(false);
        return;
    }
    if (!state.enabled)
        enable(true);
    if (mode != "inspect" && mode != "spectate" && mode != "player" && mode != "follow" && mode != "ride")
        throw std::runtime_error("Unknown control mode");
    if ((mode == "player" || mode == "ride") && !engine.playing())
        throw std::runtime_error("Start a level before controlling the player");
    copyDisplayCamera();
    // Changing an observation view keeps an explicitly selected travel clock.
    // Inspect pauses it; returning to native/player modes restores their own
    // progression ownership.
    if (mode == "follow" || mode == "player") navigation.leaveControlMode();
    navigation.followView = mode == "ride";
    navigation.viewOffset = {};
    state.captureTransition = false;
    state.playerFlight = mode == "player";
    state.progressionHeld = state.playerFlight || navigation.travel;
    state.freeCamera = mode != "follow";
    state.frozen = mode == "inspect";
    state.stepRemaining = 0;
    state.move = {};
    state.flightForwardSpeed = 0;
    if (state.playerFlight) {
        state.camera = read<Vec3>(engine.level(), off::levelPosition);
        state.heldPlayerWorld = state.world(state.camera);
        state.noclip = true;
    }
    if (mode == "ride") navigation.syncCamera();
    engine.gameSetPaused(engine.game(), false);
    state.message = mode == "inspect" ? "World PAUSED. Controls move only the camera."
                    : mode == "spectate"
                        ? "World RUNNING. Player follows its rail; controls move only the camera."
                    : mode == "ride"
                        ? "View follows player position. Drag to look in any direction."
                    : mode == "player"
                        ? "World RUNNING. Controls move the actual player; camera follows."
                        : "World RUNNING. Watching the original camera and transition.";
    event("control_mode", {{"mode", mode}});
}
void process(const Json &c) {
    std::string op = c.value("op", "");
    if (op == "batch") {
        for (auto &item : c.at("commands")) {
            if (item.value("op", "") == "batch")
                throw std::runtime_error("Nested command batches are not supported");
            process(item);
        }
        return;
    }
    if (op == "enable") {
        enable(c.value("value", true));
        return;
    }
    if (play.command(c)) return;
    if (navigation.command(c)) return;
    if (op == "snapshot") {
        needPublish = true;
        return;
    }
    if (op == "mode") {
        selectMode(c.at("value").get<std::string>());
        return;
    }
    if (op == "immortal" || op == "unlimited_balls") {
        bool value = c.value("value", true);
        if (value && !practiceMode())
            throw std::runtime_error("Practice options are available in single-player modes");
        if (op == "immortal")
            state.immortal = value;
        else
            state.unlimitedBalls = value;
        keepLastBall();
        state.message = "Practice options stay active after leaving DEV; turn them off here.";
        return;
    }
    if (!state.enabled)
        throw std::runtime_error("Enable developer mode first");
    if (op == "transition") {
        bool toGame = c.value("target", std::string("game")) == "game";
        if (toGame && engine.playing())
            throw std::runtime_error("Return to the menu before starting a game transition");
        selectMode("follow");
        state.transitionTarget = toGame ? 3 : 1;
        state.captureTransition = c.value("capture", true);
        if (toGame) {
            // Match the classic menu's "level.start 0" path. StartNewLevel is
            // a different campaign selector in 1.5.14, despite its generic name.
            alignas(8) unsigned char selector[48]{};
            engine.stringCtor(selector, "0");
            engine.gameRestart(engine.game(), selector);
            engine.stringDtor(selector);
        } else {
            write(ptr(engine.game(), off::gameMenu), off::menuVelocity, 0.f);
            engine.gameSetState(engine.game(), 1, true);
        }
        event("transition_begin",
              {{"target", state.transitionTarget}, {"capture", state.captureTransition}});
    } else if (op == "camera_home") {
        navigation.followView = false;
        state.playerFlight = false;
        state.freeCamera = true;
        copyDisplayCamera();
    } else if (op == "cruise") {
        state.cruise = c.value("value", false);
    } else if (op == "freeze") {
        state.frozen = c.value("value", true);
        state.stepRemaining = 0;
        if (!state.frozen)
            engine.gameSetPaused(engine.game(), false);
    } else if (op == "progression_hold") {
        if (!engine.playing())
            throw std::runtime_error("There is no active player in the menu");
        navigation.travel = false;
        state.progressionHeld = c.value("value", true);
        state.heldPlayerWorld = state.world(read<Vec3>(engine.level(), off::levelPosition));
        state.message =
            state.progressionHeld
                ? "Player held independently of music; simulation and streaming can step"
                : "Original music-driven player path resumes on the next update";
    } else if (op == "step") {
        state.frozen = true;
        state.stepRemaining = std::clamp(c.value("count", 1), 1, 10000);
        engine.gameSetPaused(engine.game(), false);
    } else if (op == "camera") {
        navigation.followView = false;
        state.playerFlight = false;
        bool value = c.value("value", true);
        if (value && !state.freeCamera) {
            void *display = ptr(engine.game(), off::gameDisplay);
            state.camera = read<Vec3>(display, off::displayPosition);
            state.euler = read<Quat>(display, off::displayRotation).euler();
        }
        state.freeCamera = value;
        state.move = {};
    } else if (op == "noclip")
        state.noclip = c.value("value", true);
    else if (op == "editor")
        state.editor = c.value("value", true);
    else if (op == "bounds")
        state.bounds = c.value("value", true);
    else if (op == "no_fog") {
        state.noFog = c.value("value", true);
        play.editFog = !state.noFog;
    }
    else if (op == "two_sided")
        state.twoSided = c.value("value", true);
    else if (op == "speed")
        state.speed = std::clamp(c.value("value", 1.f), .1f, 100.f);
    else if (op == "edit_pointer")
        editor.pointerInput(c);
    else if (op == "move_depth")
        editor.moveDepth(c.at("amount").get<float>());
    else if (op == "move")
        state.move = vec(c.at("value"));
    else if (op == "look") {
        if (c.contains("rotation_degrees"))
            state.euler = vec(c["rotation_degrees"]) * (PI / 180);
        else {
            state.euler.x += c.value("pitch", 0.f) * (PI / 180);
            state.euler.y += c.value("yaw", 0.f) * (PI / 180);
            state.euler.z += c.value("roll", 0.f) * (PI / 180);
            state.euler.x = std::clamp(state.euler.x, -PI * .499f, PI * .499f);
        }
    } else if (op == "teleport") {
        Vec3 p = state.local(vec(c.at("position")));
        bool player = c.value("target", std::string("camera")) == "player";
        if (player && !engine.playing())
            throw std::runtime_error(
                "Player teleport requires a loaded game; camera teleport works in the menu");
        Vec3 before = player ? read<Vec3>(engine.level(), off::levelPosition) : state.camera;
        if (player) {
            setPlayerPosition(p, !c.value("raw", false));
            if (state.playerFlight)
                state.camera = p;
        } else {
            navigation.followView = false;
            state.playerFlight = false;
            state.freeCamera = true;
            state.camera = p;
        }
        event("teleport", {{"target", player ? "player" : "camera"},
                           {"before", jvec(state.world(before))},
                           {"after", jvec(state.world(p))},
                           {"progression_held", state.progressionHeld}});
        if (player)
            state.message =
                state.progressionHeld
                    ? "Player teleported and held; Step runs original streaming at this position"
                    : "Raw pose write; native music path may restore it on update";
    } else if (op == "save_position") {
        bool player = c.value("target", std::string("camera")) == "player";
        Json saved = {
            {"position", jvec(state.world(player ? read<Vec3>(engine.level(), off::levelPosition)
                                                 : state.camera))},
            {"rotation", jvec(state.euler)}};
        if (player)
            state.savedPlayer = saved;
        else
            state.savedCamera = saved;
        state.message = "Position saved";
    } else if (op == "restore_position") {
        bool player = c.value("target", std::string("camera")) == "player";
        Json saved = player ? state.savedPlayer : state.savedCamera;
        if (saved.is_null())
            throw std::runtime_error("Save a position for this target first");
        Vec3 p = state.local(vec(saved["position"]));
        if (player)
            setPlayerPosition(p);
        else {
            state.camera = p;
            state.euler = vec(saved["rotation"]);
            state.freeCamera = true;
        }
        state.message = "Saved position restored";
    } else if (op == "section") {
        int delta = c.value("delta", 0);
        std::vector<std::pair<float, void *>> list;
        for (auto &[p, s] : editor.segments)
            if (read<uint8_t>(p, off::batchLoaded)) {
                float z = read<float>(ptr(s.room, off::roomBody), off::entityTransform + 8) +
                          (read<float>(p) + read<float>(p, 4)) * .5f;
                list.push_back({z, p});
            }
        std::sort(list.begin(), list.end(), [](auto a, auto b) { return a.first > b.first; });
        if (list.empty())
            throw std::runtime_error("No retained sections");
        bool player = c.value("target", std::string("camera")) == "player";
        Vec3 p = player ? read<Vec3>(engine.level(), off::levelPosition) : state.camera;
        int nearest = 0;
        for (size_t i = 1; i < list.size(); i++)
            if (std::abs(list[i].first - p.z) < std::abs(list[nearest].first - p.z))
                nearest = i;
        int index = std::clamp(nearest + delta, 0, static_cast<int>(list.size()) - 1);
        p.z = list[index].first;
        if (player)
            setPlayerPosition(p);
        else
            state.camera = p;
        state.message = "Moved to retained segment " + std::to_string(state.id(list[index].second));
    } else if (op == "pick") {
        if (!state.editor)
            throw std::runtime_error("Enable the editor");
        editor.pick(c.at("x"), c.at("y"), c.value("aspect", 16.f / 9), c.value("additive", false));
    } else if (op == "select") {
        if (!editor.selectId(c.at("id"), c.value("box", -1), c.value("additive", false)))
            throw std::runtime_error("Object is no longer loaded");
    } else if (op == "clear_selection") {
        editor.clearSelection();
    } else if (op == "select_all") {
        editor.selectAll(c);
    } else if (op == "move_selection") {
        editor.moveSelection(c);
    } else if (op == "apply_box_edits") {
        if (c.contains("expected_pid") && c.at("expected_pid").get<int>() != getpid())
            throw std::runtime_error("Game process changed; refresh connected targets");
        editor.applyBoxEdits(c);
    } else if (op == "reset_selection") {
        editor.resetGroup();
    } else if (op == "edit_undo" || op == "edit_redo") {
        editor.undo(op == "edit_redo");
    } else if (op == "focus_selection") {
        Bounds b = editor.groupBounds();
        if (!b.valid()) throw std::runtime_error("Select an object to focus");
        if (!state.freeCamera) copyDisplayCamera();
        navigation.followView = false;
        state.playerFlight = false;
        state.progressionHeld = false;
        state.freeCamera = true;
        state.frozen = true;
        state.stepRemaining = 0;
        state.move = {};
        void *display = ptr(engine.game(), off::gameDisplay);
        float aspect = count(display, 4) > 0 ? float(count(display, 0))/count(display, 4) : 16.f/9;
        float halfAngle = std::atan(std::tan(state.fov*PI/360)/std::max(1.f, aspect));
        float distance = std::max(2.f, (b.max-b.min).length()*.6f/std::sin(halfAngle));
        state.camera = b.center()-state.rotation().rotate({0,0,-1})*distance;
        state.message = "Framed selected objects · world paused";
    } else if (op == "transform") {
        if (!state.frozen)
            throw std::runtime_error("Freeze simulation before editing");
        editor.transform(c);
    } else if (op == "reset_object")
        editor.resetSelected();
    else if (op == "reload_section")
        editor.reloadSection();
    else if (op == "export")
        editor.exportEdits();
    else if (op == "reload_level") {
        if (!engine.playing())
            throw std::runtime_error("Start a game before rebuilding its checkpoint");
        if (c.value("from_start", false)) {
            int mode = count(ptr(engine.game(), off::gamePlayer), 0x974);
            if (mode > 2)
                throw std::runtime_error("Checkpoint-zero restart supports checkpoint modes; use "
                                         "current-checkpoint rebuild in this mode");
            // The game's own start selector is a QiString. Its native loader
            // resolves checkpoint 0 and restores the matching profile state.
            engine.stringAssign(at(engine.game(), 0x1c0), "0");
        }
        engine.gameStopLevel(engine.game());
        engine.gameStartLevel(engine.game());
        state.message = c.value("from_start", false)
                            ? "Restarted at checkpoint 0 from packaged data"
                            : "Rebuilt current checkpoint from packaged data";
    } else if (op == "fov") {
        float value = c.value("value", 80.f);
        if (!std::isfinite(value)) throw std::runtime_error("Field of view must be finite");
        state.fov = std::clamp(value, 20.f, 140.f);
        navigation.fovOverride = true;
        state.message = "Field of view updated for tools and normal play";
    }
    else if (op == "marker")
        event("marker", {{"name", c.value("name", std::string("marker"))}});
    else if (op == "raycast") {
        Vec3 start = state.local(vec(c.at("start"))), end = state.local(vec(c.at("end"))), hit,
             normal;
        void *shape = nullptr;
        bool found = engine.raycast(engine.level(), &start, &end, c.value("mask", 255), &hit,
                                    &normal, &shape, nullptr);
        state.lastRaycast = {{"hit", found},
                             {"position", jvec(state.world(hit))},
                             {"normal", jvec(normal)},
                             {"shape", pointer(shape)},
                             {"body", pointer(shape ? ptr(shape) : nullptr)}};
        event("raycast", state.lastRaycast);
    } else if (op == "quick_save") {
        if (!engine.playing())
            throw std::runtime_error("Quick-save observation requires a game");
        quickSaveHook(ptr(engine.game(), off::gamePlayer));
    } else if (op == "probe_damage") {
        if (!engine.playing())
            throw std::runtime_error("Damage probe requires a game");
        hitHook(engine.level(), -1);
        keepLastBall();
    } else
        throw std::runtime_error("Unknown command: " + op);
}
void frameHook(void *game) {
    state.frame++;
    auto now = std::chrono::steady_clock::now();
    float dt = std::clamp(std::chrono::duration<float>(now - previousFrame).count(), 0.f, .15f);
    previousFrame = now;
    std::deque<Json> commands;
    {
        std::lock_guard<std::mutex> lock(state.mutex);
        commands.swap(state.commands);
    }
    for (auto &c : commands) {
        state.lastCommand = c.value("sequence", uint64_t(0));
        try {
            process(c);
            state.error.clear();
            if (c.value("op", "") != "move" && c.value("op", "") != "look")
                event("command", {{"command", c}, {"ok", true}});
        } catch (const std::exception &e) {
            state.error = e.what();
            event("command", {{"command", c}, {"ok", false}, {"error", state.error}});
        }
        if (c.contains("request_id")) {
            state.lastRequestId = c.at("request_id");
            state.requestOk = state.error.empty();
            state.requestError = state.error;
        }
        needPublish = true;
    }
    keepLastBall();
    try { play.frame(dt); }
    catch (const std::exception &error) { state.error = error.what(); event("play_error", {{"error", error.what()}}); }
    if (state.enabled && !play.active && state.freeCamera && (!state.playerFlight || !state.frozen) &&
        (state.move.length() > 0 || (state.playerFlight && state.cruise))) {
        Vec3 delta = (state.rotation().rotate(Vec3{state.move.x, 0, -state.move.z}) +
                      Vec3{0, state.move.y, 0});
        if (delta.length() > 1)
            delta = delta.normalized();
        delta = delta * (3 * state.speed * dt);
        if (state.playerFlight && state.cruise)
            delta.z -= 3 * state.speed * dt;
        Vec3 dest = state.camera + delta;
        if (!state.noclip && engine.playing()) {
            Vec3 hit, normal;
            void *shape = nullptr;
            if (engine.raycast(engine.level(), &state.camera, &dest, 0xff, &hit, &normal, &shape,
                               nullptr))
                dest = hit + normal * .1f;
        }
        if (navigation.followView) navigation.viewOffset = navigation.viewOffset + (dest - state.camera);
        state.camera = dest;
        if (state.playerFlight) {
            state.flightForwardSpeed = dt > 0 ? std::max(0.f, -delta.z / dt) : 0.f;
            setPlayerPosition(dest);
        }
    } else {
        state.flightForwardSpeed = 0;
    }
    if (state.enabled && state.stepRemaining > 0)
        engine.gameSetPaused(game, false);
    skippedWorldUpdate = false;
    tickAfterUpdate = count(game, 0x154);
    engine.gameFrame(game);
    // The original frame loop subtracts one startup tick after its second
    // update when tick < 12. If we skipped an update, that compensation can
    // drive the counter negative forever. Preserve the last actually executed
    // update's value only in that case; ordinary frames retain native behavior.
    if (skippedWorldUpdate && count(game, 0x154) < tickAfterUpdate)
        write(game, 0x154, tickAfterUpdate);
    if (state.enabled && state.playerFlight && !engine.playing()) {
        state.playerFlight = false;
        state.progressionHeld = false;
        state.move = {};
        editor.clearSelection();
    }
    double elapsed = state.time();
    if (needPublish || elapsed - lastPublish > .3) {
        try {
            Json s = snapshot();
            std::string text = s.dump();
            {
                std::lock_guard<std::mutex> lock(state.mutex);
                state.published = text;
            }
            writeFile(state.files + "/snapshot.json", text);
            lastPublish = elapsed;
            needPublish = false;
            if (elapsed - lastSample >= 1) {
                // Keep streaming/physics observations without copying editor
                // metadata, projected lines and previous events every second.
                Json sample = s;
                for (const char *key : {"objects", "lines", "move_handles", "selection", "selection_group", "events", "navigation"})
                    sample.erase(key);
                for (const char *key : {"current_room", "next_room"})
                    if (sample.contains(key) && sample[key].is_object()) sample[key].erase("obstacles");
                event("sample", {{"snapshot", sample}});
                lastSample = elapsed;
            }
        } catch (const std::exception &e) {
            state.error = e.what();
            __android_log_print(ANDROID_LOG_ERROR, "SHDEV", "Snapshot: %s", e.what());
        }
    }
}
} // namespace
std::string readAsset(const std::string &path) {
    AAsset *asset = AAssetManager_open(state.assets, path.c_str(), AASSET_MODE_BUFFER);
    if (!asset)
        return {};
    size_t len = AAsset_getLength64(asset);
    std::string data(len, '\0');
    int n = AAsset_read(asset, data.data(), len);
    AAsset_close(asset);
    if (n < 0 || static_cast<size_t>(n) != len)
        return {};
    return data;
}
void writeFile(const std::string &path, const std::string &data) {
    std::string temp = path + ".tmp";
    {
        std::ofstream f(temp, std::ios::binary);
        f << data;
    }
    rename(temp.c_str(), path.c_str());
}
void event(const std::string &kind, Json fields) {
    fields["event"] = kind;
    fields["time"] = state.time();
    fields["frame"] = state.frame;
    fields["update"] = state.updates;
    fields["pid"] = getpid(); // Every rotated file remains attributable.
    if (engine.level()) {
        fields["player_local"] = jvec(normalPosition(engine.level()));
        fields["origin_z"] = state.originZ;
        fields["camera_local"] =
            jvec(state.enabled && state.freeCamera
                     ? state.camera
                     : read<Vec3>(ptr(engine.game(), off::gameDisplay), off::displayPosition));
    }
    diagnosticLog.append(fields.dump());
    if (kind != "sample") {
        state.events.push_back(fields);
        if (state.events.size() > 48)
            state.events.pop_front();
    }
}
Json roomSnapshot(void *room, bool details) {
    if (!room)
        return nullptr;
    void *level = ptr(room);
    float offset = read<float>(room, off::roomOffset), length = read<float>(room, off::roomLength);
    float position = normalPosition(level).z;
    Json result = {{"id", state.id(room)},
                   {"native_address", pointer(room)},
                   {"name", qiString(at(room, off::roomName))},
                   {"index", count(room, off::roomIndex)},
                   {"length", length},
                   {"offset", offset},
                   {"path_distance", -position - offset},
                   {"world_z_bounds",
                    Json::array({-offset - length + state.originZ, -offset + state.originZ})},
                   {"static_shapes", count(ptr(room, off::roomBody), off::bodyShapes)},
                   {"live_obstacles", count(room, off::roomObstacles)}};
    Json defs = Json::array();
    int n = count(room, off::roomDefs), created = 0, live = 0;
    void *data = ptr(room, off::roomDefs + 8);
    for (int i = 0; i < n && i < 20000; i++) {
        void *d = at(data, i * off::obstacleDefStride);
        bool made = read<uint8_t>(d, off::defCreated);
        void *obstacle = ptr(d, off::defInstance);
        created += made;
        live += bool(obstacle);
        if (details)
            defs.push_back({{"index", i},
                            {"name", qiString(d)},
                            {"position_in_room", jvec(read<Vec3>(d, off::defTransform))},
                            {"created_once", made},
                            {"live", bool(obstacle)},
                            {"instance", state.id(obstacle)}});
    }
    result["obstacle_definitions"] = n;
    result["created_once"] = created;
    result["definition_instances"] = live;
    result["expired_definitions"] = created - live;
    if (details) {
        result["obstacles"] = defs;
        result["batches"] = Json::array();
        for (void *p : array(room, off::roomBatches))
            result["batches"].push_back(batchSnapshot(p));
    }
    return result;
}
Json snapshot() {
    Json s = {{"version", 1},
              {"installed", state.installed},
              {"build_id", engine.buildId},
              {"enabled", state.enabled},
              {"free_camera", state.freeCamera},
              {"frozen", state.frozen},
              {"noclip", state.noclip},
              {"editor", state.editor},
              {"bounds", state.bounds},
              {"speed", state.speed},
              {"fov_horizontal", state.fov},
              {"frame", state.frame},
              {"updates", state.updates},
              {"steps_remaining", state.stepRemaining},
              {"time", state.time()},
              {"last_command", state.lastCommand},
              {"error", state.error},
              {"message", state.message},
              {"world_origin_z", state.originZ},
              {"memory", memory()},
              {"unloaded_rooms", state.unloadedRooms}};
    s["last_request_id"] = state.lastRequestId;
    s["request_ok"] = state.requestOk;
    s["request_error"] = state.requestError;
    s["raycast"] = state.lastRaycast;
    s["no_fog"] = state.noFog;
    s["two_sided"] = state.twoSided;
    s["pid"] = getpid();
    s["addon_revision"] = "5-simple-play";
    s["play_controls"] = play.info();
    s["projectiles"] = projectiles.info();
    s["saved_edits"] = editor.savedInfo();
    s["graphics"] = graphicsInfo();
    s["diagnostic_log"] = {{"current_bytes", diagnosticLog.size()}, {"file_limit_bytes", diagnosticLog.capacity()},
        {"archives", 2}, {"rotations", diagnosticLog.rotationCount()}, {"dropped", diagnosticLog.droppedCount()},
        {"error", diagnosticLog.error()}};
    s["game_updates"] = state.gameUpdates;
    s["player_flight"] = state.playerFlight;
    s["cruise"] = state.cruise;
    s["immortal"] = state.immortal;
    s["unlimited_balls"] = state.unlimitedBalls;
    s["ignored_hits"] = state.ignoredHits;
    s["prevented_game_overs"] = state.preventedGameOvers;
    s["transition_capture_pending"] = state.captureTransition;
    s["progression_held"] = state.progressionHeld;
    s["progression_corrections"] = state.progressionCorrections;
    if (state.progressionHeld)
        s["held_player_world"] = jvec(state.heldPlayerWorld);
    void *game = engine.game();
    void *level = engine.level();
    void *display = ptr(game, off::gameDisplay);
    if (!game || !level)
        return s;
    s["navigation"] = navigation.info();
    s["navigation_api_version"] = 1;
    s["original_fov_horizontal"] = read<float>(at(display, off::viewport), 0x20);
    if (!navigation.fovOverride && !(state.enabled && state.freeCamera))
        s["fov_horizontal"] = s["original_fov_horizontal"];
    Vec3 player = read<Vec3>(level, off::levelPosition);
    Vec3 camera = state.enabled && state.freeCamera ? state.camera
                                                    : read<Vec3>(display, off::displayPosition);
    Quat rot = state.enabled && state.freeCamera ? state.rotation()
                                                 : read<Quat>(display, off::displayRotation);
    s["playing"] = engine.playing();
    s["game_state"] = count(game, off::gameState);
    s["native_tick"] = count(game, 0x154);
    s["native_loaded"] = bool(read<uint8_t>(game, 0x260));
    float menuAmount = read<float>(ptr(game, off::gameMenu), off::menuTransition);
    s["menu_transition"] = menuAmount;
    s["context"] = menuAmount > .001f && menuAmount < .999f ? "transition"
                   : engine.playing()                       ? "game"
                                                            : "menu";
    s["control_target"] = (state.playerFlight || play.active) ? "player"
                          : state.enabled && navigation.followView ? "view around player"
                          : state.enabled && state.freeCamera ? "camera"
                                                              : "original camera";
    s["world_running"] = !navigation.loading && !(state.enabled && state.frozen) && !read<uint8_t>(game, off::gamePaused);
    s["native_camera_world"] = jvec(state.world(read<Vec3>(display, off::displayPosition)));
    s["native_camera_rotation_degrees"] =
        jvec(read<Quat>(display, off::displayRotation).euler() * (180 / PI));
    s["game_pause_factor"] = read<float>(game, off::gamePauseFactor);
    s["native_paused"] = bool(read<uint8_t>(game, off::gamePaused));
    s["player_mode"] = count(ptr(game, off::gamePlayer), 0x974);
    s["tutorials_suspended"] = state.enabled;
    s["tutorial_checks_skipped"] = state.tutorialChecksSkipped;
    void *tutorial = ptr(game, off::gameTutorial);
    s["active_tutorial_id"] = tutorial ? engine.tutorialId(tutorial) : 0;
    s["game_timestep"] = read<float>(game, off::gameDt);
    s["player_local"] = jvec(player);
    s["player_world"] = jvec(state.world(player));
    s["camera_local"] = jvec(camera);
    s["camera_world"] = jvec(state.world(camera));
    s["camera_rotation_degrees"] = jvec(rot.euler() * (180 / PI));
    s["camera_quaternion_xyzw"] = jquat(rot);
    s["display_distance"] = read<float>(level, off::levelDistance);
    s["music_location"] = engine.musicLocation(ptr(game, off::gameAudio));
    s["entities"] = count(level, off::levelEntities);
    s["bodies"] = count(level, off::levelBodies);
    s["profile_room_index"] = count(ptr(game, off::gamePlayer), 0x8b0);
    s["current_room"] = roomSnapshot(ptr(level, off::levelCurrent));
    s["next_room"] = roomSnapshot(ptr(level, off::levelNext));
    s["rail_phase_seconds"] = read<float>(level, off::levelRailPhase);
    s["rail_smoothed_length"] = read<float>(level, off::levelRailLength);
    s["rail_speed"] = read<float>(level, off::levelRailSpeed);
    s["player_balls"] = count(ptr(game, off::gamePlayer), 0x8b8);
    s["player_score"] = count(ptr(game, off::gamePlayer), 0x8b4);
    s["player_streak"] = count(ptr(game, off::gamePlayer), 0x8bc);
    s["quick_loaded"] = bool(read<uint8_t>(ptr(game, off::gamePlayer), 0x978));
    s["balls_in_world"] = Json::array();
    for (void *body : array(level, off::levelBodies))
        if (read<uint8_t>(body, 0x56))
            s["balls_in_world"].push_back(
                {{"id", state.id(body)},
                 {"position", jvec(state.world(read<Vec3>(body, off::entityTransform)))},
                 {"active", bool(read<uint8_t>(body, 0x15c))},
                 {"age", read<float>(body, 0xd0)},
                 {"velocity", jvec(read<Vec3>(body, 0xac))}});
    s["game_over"] = bool(read<uint8_t>(level, 0x2c8));
    s["selection"] = editor.info();
    s["selection_group"] = editor.groupInfo();
    s["editor_api_version"] = 2;
    s["objects"] = editor.objects();
    float aspect = count(display, 4) > 0 ? float(count(display, 0)) / count(display, 4) : 16.f / 9;
    s["aspect"] = aspect;
    s["lines"] = editor.lines(aspect);
    s["move_handles"] = editor.moveHandles(aspect);
    Json events = Json::array();
    int n = 0;
    for (auto it = state.events.rbegin(); it != state.events.rend() && n < 12; it++, n++) {
        Json e = *it;
        e.erase("room");
        e.erase("snapshot");
        e.erase("before");
        e.erase("after");
        events.push_back(e);
    }
    s["events"] = events;
    return s;
}
void queue(const std::string &text) {
    Json command;
    try {
        command = Json::parse(text);
        if (!command.is_object())
            throw std::runtime_error("Command must be an object");
    } catch (...) {
        command = {{"op", "invalid_json"}};
    }
    std::lock_guard<std::mutex> lock(state.mutex);
    command["sequence"] = ++state.sequence;
    if (state.commands.size() < 512)
        state.commands.push_back(std::move(command));
}
std::string published() {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.published;
}
bool install(AAssetManager *assets, const std::string &files) {
    if (state.installed)
        return true;
    state.assets = assets;
    state.files = files + "/shdev";
    mkdir(state.files.c_str(), 0700);
    diagnosticLog.open(state.files);
    if (!engine.load()) {
        state.error = engine.error;
        state.published = Json{{"installed", false}, {"error", state.error}}.dump();
        return false;
    }
    try {
        navigation.load();
        play.load();
        editor.loadSaved();
    } catch (const std::exception &error) {
        state.error = error.what();
        state.published = Json{{"installed", false}, {"error", state.error}}.dump();
        return false;
    }
    // Resolve and validate all symbols before modifying any relocation.
#define HOOK(name, fn) patches.push_back({name, reinterpret_cast<void *>(fn)});
    std::vector<std::pair<const char *, void *>> patches;
    HOOK("_ZN5Level6updateEv", levelUpdateHook);
    HOOK("_ZN4Game6updateEv", gameUpdateHook);
    HOOK("_ZN5Level12hitSomethingEi", hitHook);
    HOOK("_ZN5Level15TriggerGameOverEv", gameOverHook);
    HOOK("_ZN7Physics6removeEP4Body", physicsRemoveHook);
    HOOK("_ZN6Player9quickSaveEv", quickSaveHook);
    HOOK("_ZN6Player9quickLoadEv", quickLoadHook);
    HOOK("_ZN6Player12getHighScoreEi", checkpointScoreHook);
    HOOK("_ZN6Player14loadCheckpointEi", checkpointLoadHook);
    HOOK("_ZN4Game14updateTutorialEv", tutorialUpdateHook);
    HOOK("_ZN13TutorialUtils21checkTutorialTriggersER15TutorialManagerRK14QiArrayInplaceI11Obstacle"
         "DefLi64EERK6Playerf",
         tutorialTriggerHook);
    HOOK("_ZN5Level11handleInputERK7QiInput", inputHook);
    HOOK("_ZN5Level17createClassicBallEi", classicBallHook);
    HOOK("_ZN4Body6updateEv", bodyUpdateHook);
    HOOK("_ZN7Physics6updateEv", physicsUpdateHook);
    HOOK("_ZN5Level12loadNextRoomEv", loadNextHook);
    HOOK("_ZN5Scene4drawEv", sceneDrawHook);
    HOOK("_ZN5Level12centerCameraEv", centerHook);
    HOOK("_ZN5Level5startEv", startHook);
    HOOK("_ZN5Level7destroyEP6Entity", entityDestroyHook);
    HOOK("_ZN4RoomC1EP5LevelRK8QiStringRK7QiArrayI9ParameterEf", roomConstructorHook);
    HOOK("_ZN4RoomD1Ev", roomDestructorHook);
    HOOK("_ZN8ObstacleD1Ev", obstacleDestructorHook);
    HOOK("_ZN8Obstacle6updateEv", obstacleUpdateHook);
    HOOK("_ZN4Room13createSegmentERK8QiStringf", segmentHook);
    HOOK("_ZN11RenderBatch4loadEv", batchLoadHook);
    HOOK("_ZN4Room14createObstacleERK8QiStringRK12QiTransform3RK7QiArrayI9ParameterE",
         obstacleCreateHook);
    HOOK("_ZN4Room4drawEv", roomDrawHook);
    HOOK("_ZN4Game4drawEv", drawHook);
    HOOK("_ZNK4Room11getProgressEv", progressHook);
    HOOK("_ZN4Game5frameEv", frameHook);
#undef HOOK
    for (auto &patch : patches)
        if (!engine.hasHook(patch.first, !strcmp(patch.first, "_ZN4Body6updateEv"))) {
            state.error = "Missing hook relocation: " + std::string(patch.first);
            return false;
        }
    if (!installGraphics()) {
        state.error = "Unable to install inspection shader hooks";
        return false;
    }
    for (auto &patch : patches)
        if (!engine.hook(patch.first, patch.second, !strcmp(patch.first, "_ZN4Body6updateEv"))) {
            state.error = engine.error;
            return false;
        }
    state.installed = true;
    state.message = "Tools pause the world · Resume continues from here";
    event("instrumentation_installed", {{"build_id", engine.buildId}, {"pid", getpid()}});
    startTransport();
    __android_log_print(ANDROID_LOG_INFO, "SHDEV", "Installed for %s", engine.buildId.c_str());
    return true;
}
} // namespace shdev
