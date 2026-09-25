#pragma once
#include "math.hpp"
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

namespace shdev {
template <class T> inline T read(void *p, size_t offset = 0) {
    T value{};
    if (p)
        std::memcpy(&value, static_cast<char *>(p) + offset, sizeof(T));
    return value;
}
template <class T> inline void write(void *p, size_t offset, const T &value) {
    std::memcpy(static_cast<char *>(p) + offset, &value, sizeof(T));
}
inline void *at(void *p, size_t offset) {
    return static_cast<char *>(p) + offset;
}
inline void *ptr(void *p, size_t offset = 0) {
    return read<void *>(p, offset);
}
inline int count(void *p, size_t offset) {
    return read<int>(p, offset);
}
inline std::string qiString(void *p) {
    if (!p)
        return {};
    const char *c = read<const char *>(p);
    if (!c)
        c = static_cast<const char *>(p) + 16;
    int len = read<int>(p, 12);
    if (len < 0 || len > 4096)
        return "<invalid string>";
    return std::string(c, strnlen(c, 4096));
}
inline std::vector<void *> array(void *owner, size_t offset, int cap = 100000) {
    std::vector<void *> result;
    int n = count(owner, offset);
    void *data = ptr(owner, offset + 8);
    if (n < 0 || n > cap || (!data && n))
        return result;
    result.reserve(n);
    for (int i = 0; i < n; i++)
        result.push_back(ptr(data, i * sizeof(void *)));
    return result;
}

// These layouts were compared between both original 64-bit binaries. They are
// guarded at startup by GNU build ID. Never apply to another APK by filename.
namespace off {
constexpr size_t gameDisplay = 0x10, gameRenderer = 0x18, gameAudio = 0x28, gameLevel = 0x58,
                 gamePlayer = 0x60, gameState = 0x180, gameDt = 0x150, gamePaused = 0x1f0,
                 gamePauseFactor = 0x248, gameTutorial = 0x2f0;
constexpr size_t gameMenu = 0x258, menuTransition = 0x420, menuVelocity = 0x41c;
constexpr size_t levelCurrent = 0xf8, levelNext = 0x100, levelActive = 0x118, levelPosition = 0x11c,
                 levelRotation = 0x128, levelEntities = 0x148, levelBodies = 0x158,
                 levelDistance = 0x188, levelDefinitions = 0x250;
constexpr size_t levelRailSpeed = 0x140, levelRailPhase = 0x308, levelRailLength = 0x30c;
constexpr size_t roomName = 8, roomLength = 0x38, roomOffset = 0x3c, roomDefs = 0x98,
                 roomObstacles = 0x2ca8, roomBody = 0x2eb8, roomRootObstacle = 0x2ec0,
                 roomBatches = 0x3ff8, roomIndex = 0x47d4;
constexpr size_t obstacleDefStride = 0xb0, defTransform = 0x30, defInstance = 0x60,
                 defCreated = 0xa8;
constexpr size_t obstacleEntities = 0x28, obstacleScript = 0x160;
constexpr size_t entityType = 0x10, entityObstacle = 0x18, entityTransform = 0x20,
                 entityBounds = 0x3c;
constexpr size_t bodyShapes = 0x110, bodyJoints = 0x160;
constexpr size_t shapeMaterial = 0x138, shapePoly = 0x178, polyVertices = 0, polyEdges = 0x190,
                 polyFaces = 0x3a0;
constexpr size_t batchVbo = 8, batchIbo = 0x60, batchRoom = 0x80, batchOffset = 0x88,
                 batchLoaded = 0x8c, batchName = 0x90;
constexpr size_t vboData = 8, vboCount = 0x20, vboStride = 0x28, vboId = 0x30, iboData = 8,
                 iboCount = 0;
constexpr size_t viewport = 8, viewportPosition = 0x2c, viewportRotation = 0x38,
                 viewportStateBytes = 200, displayPosition = 0x8c4, displayRotation = 0x8d0;
} // namespace off
struct Engine {
    void *library = nullptr;
    void **globalGame = nullptr;
    uintptr_t base = 0;
    std::string buildId, error;
    void (*gameFrame)(void *) = nullptr;
    void (*gameDraw)(void *) = nullptr;
    void (*gameUpdate)(void *) = nullptr;
    void (*gameSetState)(void *, int, bool) = nullptr;
    void (*gameStartLevel)(void *) = nullptr;
    void (*gameStopLevel)(void *) = nullptr;
    void (*gameSetPaused)(void *, bool) = nullptr;
    void (*gameUpdateTutorial)(void *) = nullptr;
    void (*tutorialCheckTriggers)(void *, const void *, const void *, float) = nullptr;
    int (*tutorialId)(const void *) = nullptr;
    void (*sceneDraw)(void *) = nullptr;
    void (*levelUpdate)(void *) = nullptr;
    void (*levelInput)(void *, const void *) = nullptr;
    void *(*levelClassicBall)(void *, int) = nullptr;
    void (*levelStart)(void *) = nullptr;
    void (*levelStop)(void *) = nullptr;
    void (*levelReset)(void *, bool) = nullptr;
    void (*levelCenter)(void *) = nullptr;
    void (*levelLoadNext)(void *) = nullptr;
    void (*levelDestroy)(void *, void *) = nullptr;
    void (*levelHit)(void *, int) = nullptr;
    void (*levelGameOver)(void *) = nullptr;
    void (*physicsRemoveBody)(void *, void *) = nullptr;
    void (*physicsUpdate)(void *) = nullptr;
    void (*bodyUpdate)(void *) = nullptr;
    void (*bodyBounds)(void *) = nullptr;
    void (*playerQuickSave)(void *) = nullptr;
    bool (*playerQuickLoad)(void *) = nullptr;
    int (*playerHighScore)(void *, int) = nullptr;
    int (*playerCheckpointCount)(void *) = nullptr;
    void (*playerLoadCheckpoint)(void *, int) = nullptr;
    void (*roomDraw)(void *) = nullptr;
    float (*roomGetProgress)(const void *) = nullptr;
    void (*roomDestructor)(void *) = nullptr;
    void (*roomConstructor)(void *, void *, const void *, const void *, float) = nullptr;
    void (*obstacleDestructor)(void *) = nullptr;
    void (*obstacleUpdate)(void *) = nullptr;
    void (*batchLoad)(void *) = nullptr;
    float (*roomCreateSegment)(void *, const void *, float) = nullptr;
    void *(*roomCreateObstacle)(void *, const void *, const Transform *, const void *) = nullptr;
    void (*bodyTransform)(void *, const Transform *) = nullptr;
    void (*bodyMass)(void *) = nullptr;
    void (*polyNormals)(void *, bool) = nullptr;
    void (*viewportPosition)(void *, const Vec3 *) = nullptr;
    void (*viewportRotation)(void *, const Quat *) = nullptr;
    void (*viewportMode)(void *, float, float, float) = nullptr;
    void (*vboUpload)(void *) = nullptr;
    void (*drawTriangles)(void *, const Mat4 *, const void *, const void *, int, int) = nullptr;
    bool (*raycast)(void *, const Vec3 *, const Vec3 *, int, Vec3 *, Vec3 *, void **,
                    void *) = nullptr;
    void (*gameRestart)(void *, const void *) = nullptr;
    float (*musicLocation)(void *) = nullptr;
    void (*stringCtor)(void *, const char *) = nullptr;
    void *(*stringAssign)(void *, const char *) = nullptr;
    void (*stringDtor)(void *) = nullptr;
    bool load();
    bool hook(const char *symbol, void *replacement, bool directFunctions = false);
    bool hasHook(const char *symbol, bool directFunctions = false) const;
    void *game() const { return globalGame ? *globalGame : nullptr; }
    void *level() const { return ptr(game(), off::gameLevel); }
    bool playing() const {
        return game() && count(game(), off::gameState) == 3 &&
               read<uint8_t>(level(), off::levelActive);
    }
};
extern Engine engine;
} // namespace shdev
