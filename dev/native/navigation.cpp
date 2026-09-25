#include "navigation.hpp"
#include "play.hpp"
#include "editor.hpp"
#include <algorithm>

namespace shdev {
Navigation navigation;
namespace {
bool checkpointMode() {
    int mode = count(ptr(engine.game(), off::gamePlayer), 0x974);
    return mode >= 0 && mode <= 2;
}
int selectorIndex(const std::string &value) {
    if (value.empty() || value.size() > 2 || value.find_first_not_of("0123456789") != std::string::npos)
        return -1;
    return std::stoi(value);
}
int roomForCheckpoint(int checkpoint, bool last) {
    auto definitions = array(engine.level(), off::levelDefinitions);
    int result = -1;
    for (size_t i = 0; i < definitions.size(); ++i)
        if (navigation.checkpointForLevelEntry(count(definitions[i], 0)) == checkpoint) {
            result = static_cast<int>(i);
            if (!last) break;
        }
    return result;
}
} // namespace

void Navigation::load() {
    catalog = Json::parse(readAsset("shdev/navigation.json"));
    if (catalog.value("version", 0) != 1 || !catalog.at("levels").is_array())
        throw std::runtime_error("Invalid campaign navigation metadata");
}
int Navigation::checkpointCount() const {
    void *player = ptr(engine.game(), off::gamePlayer);
    return player && engine.playerCheckpointCount ? engine.playerCheckpointCount(player) : 0;
}
int Navigation::checkpointForLevelEntry(int entry) const {
    int size = checkpointCount();
    if (entry >= 0 && entry < size) return entry;
    // game.xml repeats the final endless level beyond the 13 actual menu
    // checkpoints. Preserve its raw index in telemetry, but group matching
    // continuation entries under that same checkpoint for navigation.
    if (size > 0 && catalog.contains("levels") && entry >= size &&
        entry < static_cast<int>(catalog["levels"].size()) &&
        catalog["levels"][entry].at("name") == catalog["levels"][size-1].at("name"))
        return size-1;
    return -1;
}
bool Navigation::available(int index) const {
    return checkpointMode() && index >= 0 && index < checkpointCount() &&
           (index == 0 || unlocked || engine.playerHighScore(ptr(engine.game(), off::gamePlayer), index) > 0);
}
int Navigation::currentCheckpoint() const {
    if (!ptr(engine.level(), off::levelCurrent)) return -1;
    auto definitions = array(engine.level(), off::levelDefinitions);
    int index = count(ptr(engine.level(), off::levelCurrent), off::roomIndex);
    return index >= 0 && index < static_cast<int>(definitions.size())
               ? checkpointForLevelEntry(count(definitions[index], 0)) : -1;
}
void Navigation::leaveControlMode() {
    if (travel) state.progressionHeld = false;
    followView = false;
    travel = false;
    direction = 1;
    cleanupDirection = 1;
    forwardSpeed = 0;
    viewOffset = {};
}
void Navigation::startBeginning() {
    leaveControlMode();
    loading = false;
    lastError.clear();
    if (unlocked && checkpointMode()) {
        int requested = selectorIndex(qiString(at(engine.game(), 0x1c0)));
        if (requested > 0 && requested < checkpointCount()) {
            pendingCheckpoint = requested;
            pendingEnd = false;
            // Load the complete native campaign through its ordinary start,
            // then reset to an actual RoomDef. No premium/profile flag is set.
            engine.stringAssign(at(engine.game(), 0x1c0), "0");
        }
    }
}
void Navigation::startFinished() {
    if (pendingCheckpoint < 0) return;
    int requested = pendingCheckpoint;
    bool end = pendingEnd, reverse = pendingReverse;
    pendingCheckpoint = -1;
    pendingEnd = pendingReverse = false;
    int room = roomForCheckpoint(requested, end);
    if (room < 0) throw std::runtime_error("The requested checkpoint has no native room definition");
    engine.playerLoadCheckpoint(ptr(engine.game(), off::gamePlayer), requested);
    if (unlocked && count(ptr(engine.game(), off::gamePlayer), 0x8b8) < 25)
        write(ptr(engine.game(), off::gamePlayer), 0x8b8, 25);
    resetRoom(room, end);
    followView = state.enabled;
    if (reverse) {
        travel = true; direction = cleanupDirection = -1; state.frozen = false;
        state.euler = {0, PI, 0};
    }
    event("checkpoint_jump", {{"checkpoint", requested}, {"room_index", room}, {"at_end", end}});
}
void Navigation::resetRoom(int index, bool atEnd, bool continuousReverse, float overflow) {
    void *level = engine.level();
    auto definitions = array(level, off::levelDefinitions);
    if (index < 0 || index >= static_cast<int>(definitions.size()))
        throw std::runtime_error("Room index is outside the loaded campaign definitions");
    void *before = ptr(level, off::levelCurrent);
    int oldIndex = before ? count(before, off::roomIndex) : -1;
    float seamWorldZ = before ? state.originZ - read<float>(before, off::roomOffset) : 0;
    Vec3 oldPlayer = state.world(read<Vec3>(level, off::levelPosition));
    Vec3 oldCamera = state.world(state.camera);
    int pendingSteps = state.stepRemaining;
    editor.clear();
    rebuilding = true;
    write(ptr(engine.game(), off::gamePlayer), 0x8b0, index);
    state.originZ = 0;
    try {
        engine.levelReset(level, false);
    } catch (...) {
        rebuilding = false;
        throw;
    }
    rebuilding = false;
    void *room = ptr(level, off::levelCurrent);
    if (!room || count(room, off::roomIndex) != index)
        throw std::runtime_error("The native room reset did not create its requested definition");
    float length = read<float>(room, off::roomLength);
    if (!std::isfinite(length) || length <= 0)
        throw std::runtime_error("The native room has an invalid length");
    state.originZ = continuousReverse ? seamWorldZ + length : 0;
    Vec3 pose = continuousReverse ? Vec3{oldPlayer.x, oldPlayer.y, -length + overflow}
                                 : Vec3{0, 1, atEnd ? -std::max(0.f, length - 1.f) : 0};
    write(level, off::levelPosition, pose);
    state.heldPlayerWorld = state.world(pose);
    state.progressionHeld = state.enabled && (travel || atEnd);
    state.playerFlight = false;
    if (!continuousReverse || !play.active) state.move = {};
    // Game::update already consumed one permitted step before discovering
    // this boundary. Rebuilding runs no Level::update; preserve that step and
    // every remaining requested step until the new room's buffers are ready.
    state.stepRemaining = continuousReverse && state.frozen ? pendingSteps + 1 : 0;
    // Android dialogs can leave the native pause flag set. The developer
    // freeze and loading guard own simulation suspension for this operation.
    engine.gameSetPaused(engine.game(), false);
    if (state.enabled) {
        state.freeCamera = true;
        state.camera = continuousReverse && !followView ? state.local(oldCamera) : pose + viewOffset;
        if (!continuousReverse) {
            state.euler = {0, atEnd ? PI : 0, 0};
            if (play.editing || play.tools) { play.resumeEuler = state.euler; play.haveResumeView = true; }
        }
    }
    // Original draw frames incrementally prepare every RenderBatch. Keep
    // physics/progression stopped until those actual buffers are ready.
    loading = true;
    lastError.clear();
    ++roomRebuilds;
    state.message = "Loading " + qiString(at(room, off::roomName)) + " from original room data";
    event("room_reconstructed", {{"from_index", oldIndex}, {"to_index", index},
                                  {"room_id", state.id(room)}, {"reverse_boundary", continuousReverse},
                                  {"origin_z", state.originZ}, {"player_world", jvec(state.world(pose))}});
}
void Navigation::jumpCheckpoint(int index, bool atEnd) {
    if (!available(index)) throw std::runtime_error("Unlock all levels or choose a reached checkpoint first");
    if (!engine.playing() || !read<uint8_t>(engine.level(), 0x119)) {
        pendingCheckpoint = index;
        pendingEnd = atEnd;
        if (engine.playing()) {
            engine.gameStopLevel(engine.game());
            engine.stringAssign(at(engine.game(), 0x1c0), "0");
            engine.gameStartLevel(engine.game());
        } else {
            alignas(8) unsigned char selector[48]{};
            engine.stringCtor(selector, "0");
            engine.gameRestart(engine.game(), selector);
            engine.stringDtor(selector);
        }
        return;
    }
    int room = roomForCheckpoint(index, atEnd);
    if (room < 0) throw std::runtime_error("This campaign does not contain the selected checkpoint");
    engine.playerLoadCheckpoint(ptr(engine.game(), off::gamePlayer), index);
    if (unlocked && count(ptr(engine.game(), off::gamePlayer), 0x8b8) < 25)
        write(ptr(engine.game(), off::gamePlayer), 0x8b8, 25);
    resetRoom(room, atEnd);
    followView = true;
    event("checkpoint_jump", {{"checkpoint", index}, {"room_index", room}, {"at_end", atEnd}});
}
bool Navigation::waitingForGeometry() {
    if (!loading) return false;
    void *room = ptr(engine.level(), off::levelCurrent);
    if (!room) return true;
    for (void *batch : array(room, off::roomBatches))
        if (!read<uint8_t>(batch, off::batchLoaded)) return true;
    if (read<float>(ptr(engine.game(), off::gameMenu), off::menuTransition) > .001f) return true;
    loading = false;
    state.message = "Room ready · " + std::string(state.frozen ? "world paused" : "world running");
    event("navigation_ready", {{"room_index", count(room, off::roomIndex)}, {"room_id", state.id(room)}});
    return false;
}
void Navigation::restorePassedObjects() {
    void *room = ptr(engine.level(), off::levelCurrent);
    if (!room) return;
    int n = count(room, off::roomDefs);
    if (n < 0 || n > 4096) throw std::runtime_error("Invalid native obstacle definition count");
    void *data = ptr(room, off::roomDefs + 8);
    int restored = 0;
    for (int i = 0; i < n; ++i) {
        void *definition = at(data, i * off::obstacleDefStride);
        if (!ptr(definition, off::defInstance) && read<uint8_t>(definition, off::defCreated)) {
            write<uint8_t>(definition, off::defCreated, 0);
            ++restored;
        }
    }
    restoredDefinitions += restored;
    if (restored) event("travel_definitions_rearmed", {{"room_id", state.id(room)}, {"count", restored},
                                                      {"direction", cleanupDirection}});
}
void Navigation::prepareUpdate() {
    if (!state.enabled || !travel || !engine.playing() || loading) return;
    void *level = engine.level(), *room = ptr(level, off::levelCurrent);
    if (!room) return;
    Vec3 pose = read<Vec3>(level, off::levelPosition);
    float offset = read<float>(room, off::roomOffset);
    if ((direction < 0 || (play.active && cleanupDirection < 0)) && pose.z + offset > 0) {
        int previous = count(room, off::roomIndex) - 1;
        if (previous < 0) {
            pose.z = -offset;
            direction = 0;
            if (play.active) play.stopped = true;
            state.message = "Start of campaign reached · player held";
            event("reverse_campaign_start");
        } else {
            resetRoom(previous, true, true, pose.z + offset);
            return;
        }
    }
    // The original non-boss rail normalizes a room to a 32-second music
    // phrase. This explicit travel clock uses that nominal pace, independent
    // of view direction and the audio-driven smoothing of normal gameplay.
    float dt = read<float>(engine.game(), off::gameDt);
    if (!std::isfinite(dt) || dt < 0 || dt > .5f) throw std::runtime_error("Invalid native update timestep");
    forwardSpeed = direction * read<float>(room, off::roomLength) / 32.f * multiplier;
    float deltaZ = -forwardSpeed * dt;
    pose.z += deltaZ;
    lastTravelDt = dt;
    travelSeconds += dt;
    travelWorldZ += deltaZ;
    ++travelUpdates;
    write(level, off::levelPosition, pose);
    state.heldPlayerWorld = state.world(pose);
    state.progressionHeld = true;
}
void Navigation::finishUpdate() { syncCamera(); }
void Navigation::syncCamera() {
    if (state.enabled && followView && engine.playing())
        state.camera = read<Vec3>(engine.level(), off::levelPosition) + viewOffset;
}
void Navigation::recordProjection(void *viewport) {
    drawFov = read<float>(viewport, 0x20);
    drawProjectionX = read<float>(viewport, 0x48);
    drawProjectionY = read<float>(viewport, 0x5c);
    drawFrame = state.frame;
}
bool Navigation::command(const Json &c) {
    std::string op = c.value("op", "");
    if (op == "unlock_levels") {
        unlocked = c.value("value", true);
        state.message = unlocked ? "All campaign checkpoints unlocked for this session"
                                 : "Original checkpoint access restored";
        event("checkpoint_access", {{"unlocked", unlocked}});
    } else if (op == "fov_original") {
        if (!ptr(engine.game(), off::gameDisplay)) throw std::runtime_error("The renderer is still starting");
        fovOverride = false;
        state.fov = read<float>(at(ptr(engine.game(), off::gameDisplay), off::viewport), 0x20);
        state.message = "Original field of view restored";
    } else if (op == "travel_speed") {
        float value = c.at("value").get<float>();
        if (!std::isfinite(value) || value < .1f || value > 100)
            throw std::runtime_error("Travel speed must be between 0.1 and 100");
        multiplier = value;
    } else if (op == "travel") {
        if (!state.enabled || !engine.playing() || !checkpointMode())
            throw std::runtime_error("Open developer tools in a checkpoint game first");
        int requested = c.value("direction", 1);
        if (requested < -1 || requested > 1) throw std::runtime_error("Travel direction must be -1, 0 or 1");
        bool directionStart = requested != 0 && (!travel || cleanupDirection != requested);
        travel = c.value("enabled", true);
        direction = requested;
        if (travel && requested != 0) cleanupDirection = requested;
        if (!travel || direction == 0) forwardSpeed = 0;
        if (!state.frozen) engine.gameSetPaused(engine.game(), false);
        state.playerFlight = false;
        state.progressionHeld = travel;
        state.heldPlayerWorld = state.world(read<Vec3>(engine.level(), off::levelPosition));
        if (directionStart && travel) restorePassedObjects();
        state.message = !travel ? "Original music-driven path restored"
                        : direction > 0 ? "Forward travel · view direction is independent"
                        : direction < 0 ? "Reverse travel · discarded rooms will be rebuilt"
                                        : "Player held · world simulation can continue";
        event("travel_direction", {{"enabled", travel}, {"direction", direction}, {"multiplier", multiplier}});
    } else if (op == "jump_level" || op == "reverse_level") {
        if (!state.enabled) throw std::runtime_error("Open developer tools first");
        int checkpoint = c.value("index", std::max(0, currentCheckpoint()));
        bool reverse = op == "reverse_level";
        if (!available(checkpoint)) throw std::runtime_error("Unlock all levels or choose a reached checkpoint first");
        if (reverse) pendingReverse = true;
        jumpCheckpoint(checkpoint, reverse || c.value("at_end", false));
        if (reverse && pendingCheckpoint < 0) {
            pendingReverse = false;
            travel = true; direction = cleanupDirection = -1; state.progressionHeld = true;
            state.frozen = false; state.euler = {0, PI, 0};
            restorePassedObjects();
        }
    } else if (op == "jump_room") {
        if (!state.enabled || !engine.playing() || !checkpointMode())
            throw std::runtime_error("Open a checkpoint game first");
        auto definitions = array(engine.level(), off::levelDefinitions);
        int index = c.at("index").get<int>();
        if (index < 0 || index >= static_cast<int>(definitions.size()) ||
            !available(checkpointForLevelEntry(count(definitions[index], 0))))
            throw std::runtime_error("Choose an available room in the current campaign");
        resetRoom(index, c.value("at_end", false));
        followView = true;
    } else return false;
    return true;
}
Json Navigation::info() {
    Json result = {{"follow_player_view", followView}, {"travel_enabled", travel},
                   {"direction", direction}, {"speed_multiplier", multiplier},
                   {"obstacle_cleanup_direction", cleanupDirection},
                   {"velocity_world_z", -forwardSpeed}, {"loading", loading},
                   {"travel_seconds", travelSeconds}, {"travel_delta_world_z", travelWorldZ},
                   {"travel_updates", travelUpdates}, {"last_travel_dt", lastTravelDt},
                   {"error", lastError},
                   {"unlocked", unlocked}, {"fov_override", fovOverride},
                   {"last_draw_fov", drawFov}, {"last_draw_projection_x", drawProjectionX},
                   {"last_draw_projection_y", drawProjectionY}, {"last_draw_frame", drawFrame},
                   {"last_input_fov", inputFov},
                   {"room_rebuilds", roomRebuilds}, {"restored_obstacle_definitions", restoredDefinitions},
                   {"current_checkpoint", currentCheckpoint()}, {"checkpoint_mode", checkpointMode()},
                   {"view_offset", jvec(viewOffset)}, {"levels", Json::array()}, {"rooms", Json::array()}};
    if (catalog.is_object()) {
        int size = std::min(checkpointCount(), static_cast<int>(catalog.at("levels").size()));
        for (int i = 0; i < size; ++i) {
            auto entry = catalog["levels"][i];
            entry.erase("rooms");
            entry["available"] = available(i);
            entry["recorded_balls"] = engine.playerHighScore(ptr(engine.game(), off::gamePlayer), i);
            result["levels"].push_back(entry);
        }
    }
    auto definitions = array(engine.level(), off::levelDefinitions);
    void *currentRoom = ptr(engine.level(), off::levelCurrent);
    int current = currentRoom ? count(currentRoom, off::roomIndex) : -1;
    for (size_t i = 0; i < definitions.size(); ++i) {
        void *definition = definitions[i];
        int levelEntry = count(definition, 0), checkpoint = checkpointForLevelEntry(levelEntry);
        result["rooms"].push_back({{"index", i}, {"checkpoint", checkpoint},
                                    {"source_level_entry", levelEntry},
                                    {"name", qiString(at(definition, 8))},
                                    {"display_length", count(definition, 0x48)},
                                    {"current", static_cast<int>(i) == current},
                                    {"available", available(checkpoint)}});
    }
    return result;
}
} // namespace shdev
