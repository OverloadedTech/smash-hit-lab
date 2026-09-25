#include "play.hpp"
#include "editor.hpp"
#include "navigation.hpp"
#include "storage.hpp"

namespace shdev {
PlayControls play;
namespace {
float number(const Json &value, float low, float high, const char *name) {
    if (!value.is_number()) throw std::runtime_error(std::string(name) + " must be a number");
    float result = value.get<float>();
    if (!std::isfinite(result) || result < low || result > high)
        throw std::runtime_error(std::string(name) + " is outside the supported range");
    return result;
}
float shortest(float v) { return std::remainder(v, 2 * PI); }
void readyDisplay() {
    if (!engine.game() || !ptr(engine.game(), off::gameDisplay))
        throw std::runtime_error("The game is still starting");
}
}
void PlayControls::load() {
    try {
        Json data = readLocalJson(state.files + "/controls.json", 16384);
        if (data.is_null()) return;
        if (data.at("version") != 1) throw std::runtime_error("Unknown controls file version");
        const Json &s = data.at("settings");
        // Validate the complete file before accepting any setting.
        float move = number(s.at("move_speed"), 1, 100, "Move speed");
        float travel = number(s.at("travel_speed"), .1f, 25, "Travel speed");
        float look = number(s.at("look_speed"), .25f, 4, "Look speed");
        float fov = number(s.at("fov"), 20, 140, "Field of view");
        bool a = s.at("automatic").get<bool>(), p = s.at("play_fog").get<bool>(),
             e = s.at("edit_fog").get<bool>(), saved = s.at("use_saved_edits").get<bool>(),
             lensEnabled = s.at("custom_fov").get<bool>();
        moveSpeed = move; travelSpeed = travel; lookSpeed = look; lens = fov;
        automatic = a; playFog = p; editFog = e; savedEdits = saved; customFov = lensEnabled;
        state.speed = moveSpeed / 3;
        state.noFog = !editFog;
        if (customFov) { state.fov = lens; navigation.fovOverride = true; }
    } catch (const std::exception &error) {
        settingsError = error.what();
        event("controls_load_error", {{"error", settingsError}});
    }
}
void PlayControls::saveSettings() {
    saveLocalJson(state.files + "/controls.json", {{"version", 1}, {"settings", {
        {"automatic", automatic}, {"move_speed", moveSpeed}, {"travel_speed", travelSpeed},
        {"look_speed", lookSpeed}, {"fov", lens}, {"custom_fov", customFov},
        {"play_fog", playFog}, {"edit_fog", editFog}, {"use_saved_edits", savedEdits}}}});
    settingsError.clear();
}
void PlayControls::leaveLegacy() {
    active = editing = exploring = tools = startPending = turning = false;
    haveResumeView = false;
}
void PlayControls::levelStarted() {
    startPending = automatic && !state.enabled;
    if (active) { active = false; startPending = true; }
    haveResumeView = false;
}
void PlayControls::configureTravel() {
    navigation.followView = true;
    navigation.viewOffset = {};
    navigation.travel = true;
    navigation.direction = rails && !stopped ? (backward ? -1 : 1) : 0;
    navigation.multiplier = travelSpeed;
    state.progressionHeld = true;
    state.playerFlight = false;
}
void PlayControls::enter() {
    readyDisplay();
    if (!engine.playing()) throw std::runtime_error("Start a game to use player controls");
    if (count(ptr(engine.game(), off::gamePlayer), 0x974) > 3)
        throw std::runtime_error("First-person controls are available in single-player modes");
    if (!state.enabled && !navigation.fovOverride)
        state.fov = read<float>(at(ptr(engine.game(), off::gameDisplay), off::viewport), 0x20);
    if (!active) {
        state.euler = haveResumeView ? resumeEuler : read<Quat>(engine.level(), off::levelRotation).euler();
        haveResumeView = true;
    }
    state.enabled = state.freeCamera = true;
    state.frozen = false; state.stepRemaining = 0; state.captureTransition = false;
    state.editor = false; state.bounds = false; state.move = {};
    active = true; editing = exploring = tools = startPending = false; turning = false;
    configureTravel();
    state.heldPlayerWorld = state.world(read<Vec3>(engine.level(), off::levelPosition));
    navigation.syncCamera();
    engine.gameSetPaused(engine.game(), false);
    editor.clearSelection();
    state.message = stopped ? "Movement stopped · looking and shooting still work" : "Tap to shoot · drag to look";
    event("play_controls", {{"mode", rails ? "rails" : "free"}, {"player_world", jvec(state.heldPlayerWorld)}});
}
void PlayControls::pause(bool edit) {
    readyDisplay();
    if (!editing && !exploring && !tools) {
        if (active) { resumeEuler = state.euler; haveResumeView = true; }
        else {
            void *display = ptr(engine.game(), off::gameDisplay);
            state.camera = read<Vec3>(display, off::displayPosition);
            state.euler = read<Quat>(display, off::displayRotation).euler();
            resumeEuler = state.euler; haveResumeView = true;
        }
    }
    active = exploring = false; editing = edit; tools = !edit; turning = startPending = false;
    state.enabled = state.freeCamera = state.frozen = true;
    state.editor = edit; state.bounds = false; state.stepRemaining = 0; state.move = {};
    state.playerFlight = false; state.captureTransition = false;
    navigation.followView = false;
    state.speed = moveSpeed / 3;
    state.heldPlayerWorld = state.world(read<Vec3>(engine.level(), off::levelPosition));
    state.progressionHeld = engine.playing();
    engine.gameSetPaused(engine.game(), false);
    state.message = edit ? "Paused · drag an object, then Save & resume" : "Game paused while tools are open";
    event("tools_paused", {{"editing", edit}, {"player_world", jvec(state.heldPlayerWorld)}});
}
void PlayControls::frame(float dt) {
    if (active && read<uint8_t>(engine.game(), off::gamePaused)) pause(false);
    if (startPending && count(ptr(engine.game(), off::gamePlayer), 0x974) > 3) startPending = false;
    if (startPending && engine.playing() && !navigation.loading &&
        read<float>(ptr(engine.game(), off::gameMenu), off::menuTransition) <= .001f) enter();
    if (active && !engine.playing()) {
        active = false; haveResumeView = false; turning = false;
        state.enabled = state.freeCamera = state.progressionHeld = false;
        state.move = {}; navigation.leaveControlMode(); editor.clearSelection();
    }
    if (!active || state.frozen || !turning) return;
    float maxStep = PI * lookSpeed * dt;
    Vec3 delta{turnTarget.x - state.euler.x, shortest(turnTarget.y - state.euler.y), -state.euler.z};
    float length = delta.length();
    if (length <= maxStep || length < .0001f) { state.euler = turnTarget; turning = false; }
    else state.euler = state.euler + delta * (maxStep / length);
    turnSeconds += dt;
}
void PlayControls::prepareUpdate() {
    if (!active || !engine.playing() || navigation.loading) return;
    configureTravel();
    void *level = engine.level(), *room = ptr(level, off::levelCurrent);
    float dt = read<float>(engine.game(), off::gameDt);
    if (!std::isfinite(dt) || dt < 0 || dt > .5f) throw std::runtime_error("Invalid player movement timestep");
    Vec3 input = stopped ? Vec3{} : state.move;
    Vec3 delta = state.rotation().rotate({input.x, 0, -input.z}) + Vec3{0, input.y, 0};
    if (delta.length() > 1) delta = delta.normalized();
    delta = delta * (moveSpeed * dt);
    Vec3 position = read<Vec3>(level, off::levelPosition), dest = position + delta;
    if (!state.noclip && delta.length() > 0) {
        Vec3 hit, normal; void *shape = nullptr;
        if (engine.raycast(level, &position, &dest, 0xff, &hit, &normal, &shape, nullptr))
            dest = hit + normal * .1f;
    }
    float railZ = room ? -navigation.direction * read<float>(room, off::roomLength) / 32.f * travelSpeed * dt : 0;
    float totalZ = (dest.z - position.z) + railZ;
    int sense = std::abs(totalZ) > .000001f ? (totalZ > 0 ? -1 : 1) : navigation.cleanupDirection;
    if (sense != navigation.cleanupDirection) {
        navigation.cleanupDirection = sense;
        navigation.restorePassedObjects();
    }
    write(level, off::levelPosition, dest);
    state.heldPlayerWorld = state.world(dest);
    moved = moved + dest - position;
    movementSeconds += dt; ++movementUpdates;
}
bool PlayControls::fogHidden() const {
    return state.enabled && !active ? !editFog : !playFog;
}
Json PlayControls::info() const {
    return {{"version", 1}, {"active", active}, {"editing", editing}, {"exploring", exploring}, {"tools_paused", tools},
        {"automatic", automatic}, {"rails", rails}, {"stopped", stopped}, {"backward", backward},
        {"move_speed", moveSpeed}, {"travel_speed", travelSpeed}, {"look_speed", lookSpeed},
        {"play_fog", playFog}, {"edit_fog", editFog}, {"use_saved_edits", savedEdits},
        {"fog_hidden", fogHidden()}, {"custom_fov", customFov}, {"fov", lens},
        {"turning", turning}, {"turn_target_degrees", jvec(turnTarget * (180 / PI))},
        {"movement_seconds", movementSeconds}, {"movement_updates", movementUpdates},
        {"shot_spawns", shotSpawns}, {"last_shot", lastShot},
        {"moved_by_controls", jvec(moved)}, {"turn_seconds", turnSeconds}, {"settings_error", settingsError}};
}
bool PlayControls::command(const Json &c) {
    std::string op = c.value("op", "");
    if (op == "workspace") {
        std::string value = c.at("value").get<std::string>();
        if (value == "play" || value == "resume") {
            float transition = read<float>(ptr(engine.game(), off::gameMenu), off::menuTransition);
            if (transition > .001f && transition < .999f) {
                // Finish the original animated camera transition, then attach
                // Play controls at its normal endpoint if enabled.
                leaveLegacy(); startPending = automatic && engine.playing();
                state.enabled = state.freeCamera = state.progressionHeld = false;
                state.move = {}; state.stepRemaining = 0; navigation.leaveControlMode();
                engine.gameSetPaused(engine.game(), false);
            } else if (engine.playing()) enter();
            else {
                leaveLegacy(); state.enabled = state.freeCamera = state.progressionHeld = false;
                state.move = {}; state.stepRemaining = 0; navigation.leaveControlMode();
                engine.gameSetPaused(engine.game(), false);
            }
        } else if (value == "edit" || value == "tools") pause(value == "edit");
        else if (value == "explore") {
            pause(false); tools = false; exploring = true;
            state.message = "Paused · drag to look · use the stick and Up / Down to fly";
        }
        else if (value == "classic") {
            if (engine.playing() && !c.value("restart", false))
                throw std::runtime_error("Original controls start a fresh run; use Resume to continue here");
            int mode = count(ptr(engine.game(), off::gamePlayer), 0x974);
            if (engine.playing() && (mode < 0 || mode > 5))
                throw std::runtime_error("The current game mode has no verified new-run selector");
            automatic = false; saveSettings(); leaveLegacy(); navigation.leaveControlMode();
            state.enabled = state.freeCamera = state.progressionHeld = state.playerFlight = false;
            state.frozen = state.captureTransition = false; state.stepRemaining = 0; state.move = {};
            editor.clearSelection();
            if (engine.playing()) {
                // RestartLevel only enters gameplay when Game is in another
                // state. Calling it inside state 3 leaves the old room alive
                // and starts a menu transition. Rebuild through the original
                // stop/start lifecycle, using its verified mode selectors.
                const char *selector = mode == 3 ? "level:zen" : mode == 4 ? "level:versus"
                                     : mode == 5 ? "level:coop" : "0";
                engine.stringAssign(at(engine.game(), 0x1c0), selector);
                engine.gameStopLevel(engine.game());
                engine.gameStartLevel(engine.game());
                event("original_controls_restart", {{"mode", mode}, {"selector", selector}});
            }
            engine.gameSetPaused(engine.game(), false);
        } else throw std::runtime_error("Choose Play, Edit or Tools");
    } else if (op == "play_mode") {
        std::string mode = c.at("value").get<std::string>();
        if (mode != "rails" && mode != "free") throw std::runtime_error("Choose Rails or Free move");
        rails = mode == "rails"; stopped = false;
        if (!active) enter(); else { state.move = {}; configureTravel(); }
    } else if (op == "play_stop") {
        if (!active) throw std::runtime_error("Resume play first");
        stopped = c.at("value").get<bool>(); state.move = {}; configureTravel();
        state.message = stopped ? "Movement stopped · physics and shooting continue" : "Movement resumed";
    } else if (op == "play_backward") {
        if (!active) throw std::runtime_error("Resume play first");
        backward = c.at("value").get<bool>(); rails = true; stopped = false; configureTravel();
    } else if (op == "play_move") {
        const auto &input = c.at("value");
        if (!input.is_array() || input.size() != 3) throw std::runtime_error("Movement needs three axes");
        Vec3 v = vec(input);
        state.move = {std::clamp(v.x, -1.f, 1.f), std::clamp(v.y, -1.f, 1.f), std::clamp(v.z, -1.f, 1.f)};
        if (!active && !editing && !exploring) state.move = {};
    } else if (op == "play_look") {
        if (!active && !editing && !exploring) return true;
        float yaw = c.value("yaw", 0.f), pitch = c.value("pitch", 0.f);
        if (!std::isfinite(yaw) || !std::isfinite(pitch)) throw std::runtime_error("Look angles must be finite");
        turning = false; state.euler.y += yaw * lookSpeed * PI / 180;
        state.euler.x = std::clamp(state.euler.x + pitch * lookSpeed * PI / 180, -PI * .49f, PI * .49f);
        state.euler.z = 0;
    } else if (op == "play_face") {
        if (!active) throw std::runtime_error("Resume play to turn");
        float yaw = number(c.at("yaw"), -3600, 3600, "Look direction");
        turnTarget = {0, yaw * PI / 180, 0}; turning = true;
    } else if (op == "control_settings") {
        // Transactional persistence: restore in-memory settings if saving fails.
        PlayControls before = *this;
        try {
            if (c.contains("move_speed")) moveSpeed = number(c.at("move_speed"), 1, 100, "Move speed");
            if (c.contains("travel_speed")) travelSpeed = number(c.at("travel_speed"), .1f, 25, "Travel speed");
            if (c.contains("look_speed")) lookSpeed = number(c.at("look_speed"), .25f, 4, "Look speed");
            if (c.contains("fov")) { lens = number(c.at("fov"), 20, 140, "Field of view"); customFov = true; }
            if (c.contains("custom_fov")) customFov = c.at("custom_fov").get<bool>();
            if (c.contains("play_fog")) playFog = c.at("play_fog").get<bool>();
            if (c.contains("edit_fog")) editFog = c.at("edit_fog").get<bool>();
            if (c.contains("use_saved_edits")) savedEdits = c.at("use_saved_edits").get<bool>();
            if (c.contains("automatic")) automatic = c.at("automatic").get<bool>();
            saveSettings();
        } catch (...) { *this = before; throw; }
        state.speed = moveSpeed / 3; state.noFog = !editFog;
        navigation.multiplier = travelSpeed; navigation.fovOverride = customFov;
        state.fov = customFov ? lens : read<float>(at(ptr(engine.game(), off::gameDisplay), off::viewport), 0x20);
        state.message = "Settings saved";
    } else if (op == "save_level_edits") {
        editor.saveChanges();
        if (c.value("resume", false)) enter();
    } else if (op == "save_replay" || op == "replay_level") {
        if (op == "save_replay") editor.saveChanges();
        navigation.jumpCheckpoint(c.at("index").get<int>(), false);
        if (engine.playing()) enter();
    } else if (op == "forget_level_edits") editor.forgetSaved();
    else return false;
    return true;
}
}
