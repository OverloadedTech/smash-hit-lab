#pragma once
#include "../vendor/json.hpp"
#include "engine.hpp"
#include <android/asset_manager.h>
#include <chrono>
#include <atomic>
#include <deque>
#include <map>
#include <mutex>
#include <string>

namespace shdev {
using Json = nlohmann::json;
inline Json jvec(Vec3 v) {
    return Json::array({v.x, v.y, v.z});
}
inline Json jquat(Quat q) {
    return Json::array({q.x, q.y, q.z, q.w});
}
inline Vec3 vec(const Json &a, Vec3 fallback = {}) {
    if (!a.is_array() || a.size() != 3)
        return fallback;
    Vec3 v{a[0].get<float>(), a[1].get<float>(), a[2].get<float>()};
    if (!v.finite())
        throw std::runtime_error("Coordinates must be finite");
    return v;
}
inline std::string pointer(void *p) {
    char s[32];
    snprintf(s, sizeof(s), "0x%llx",
             static_cast<unsigned long long>(reinterpret_cast<uintptr_t>(p)));
    return s;
}
struct State {
    bool installed = false, enabled = false, freeCamera = false, frozen = true, noclip = true,
         editor = true, bounds = true, renderOverride = false;
    bool noFog = true, twoSided = true;
    bool progressionHeld = false;
    bool playerFlight = false, cruise = false, immortal = false, unlimitedBalls = false;
    bool captureTransition = false;
    int transitionTarget = 0;
    float flightForwardSpeed = 0;
    uint64_t gameUpdates = 0, ignoredHits = 0, preventedGameOvers = 0;
    std::atomic<uint64_t> shotSerial{0}; // UI reads only this acknowledgement, never live engine memory.
    Vec3 heldPlayerWorld;
    uint64_t progressionCorrections = 0;
    uint64_t tutorialChecksSkipped = 0;
    Vec3 renderNormalPosition;
    float speed = 1, fov = 60, farClip = 2000;
    Vec3 camera, euler, move;
    float originZ = 0;
    int stepRemaining = 0;
    uint64_t frame = 0, updates = 0, sequence = 0, lastCommand = 0, nextId = 1;
    std::string files, error, message = "Tap Tools in the menu or in a game";
    std::string lastRequestId, requestError;
    bool requestOk = true;
    Json lastRaycast;
    AAssetManager *assets = nullptr;
    std::map<void *, uint64_t> ids;
    std::deque<Json> events;
    std::vector<Json> unloadedRooms;
    Json savedCamera, savedPlayer;
    std::mutex mutex;
    std::deque<Json> commands;
    std::string published = "{}";
    std::chrono::steady_clock::time_point begun = std::chrono::steady_clock::now();
    Vec3 world(Vec3 p) const {
        p.z += originZ;
        return p;
    }
    Vec3 local(Vec3 p) const {
        p.z -= originZ;
        return p;
    }
    Quat rotation() const { return Quat::euler(euler); }
    double time() const {
        return std::chrono::duration<double>(std::chrono::steady_clock::now() - begun).count();
    }
    uint64_t id(void *p) {
        if (!p)
            return 0;
        auto &id = ids[p];
        if (!id)
            id = nextId++;
        return id;
    }
};
extern State state;
void event(const std::string &kind, Json fields = Json::object());
Json roomSnapshot(void *room, bool details = true);
Json snapshot();
bool install(AAssetManager *assets, const std::string &files);
void queue(const std::string &command);
std::string published();
std::string readAsset(const std::string &path);
void writeFile(const std::string &path, const std::string &data);
bool installGraphics();
Json graphicsInfo();
void startTransport();
} // namespace shdev
