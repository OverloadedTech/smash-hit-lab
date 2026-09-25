#include "engine.hpp"
#include <android/log.h>
#include <cstdio>
#include <dlfcn.h>
#include <elf.h>
#include <link.h>
#include <map>
#include <sys/mman.h>
#include <unistd.h>

namespace shdev {
Engine engine;
namespace {
std::map<std::string, std::vector<void **>> slots;
std::map<std::string, std::vector<void **>> directFunctionSlots;
int inspect(dl_phdr_info *info, size_t, void *) {
    const char *name = strrchr(info->dlpi_name, '/');
    name = name ? name + 1 : info->dlpi_name;
    if (strcmp(name, "libsmashhit.so"))
        return 0;
    engine.base = info->dlpi_addr;
    const ElfW(Dyn) *dynamic = nullptr;
    for (int i = 0; i < info->dlpi_phnum; i++) {
        const auto &ph = info->dlpi_phdr[i];
        if (ph.p_type == PT_DYNAMIC)
            dynamic = reinterpret_cast<const ElfW(Dyn) *>(engine.base + ph.p_vaddr);
        if (ph.p_type == PT_NOTE) {
            uintptr_t p = engine.base + ph.p_vaddr, end = p + ph.p_memsz;
            while (p + sizeof(ElfW(Nhdr)) <= end) {
                const auto *nh = reinterpret_cast<const ElfW(Nhdr) *>(p);
                p += sizeof(*nh);
                uintptr_t np = p;
                p += (nh->n_namesz + 3) & ~3u;
                uintptr_t dp = p;
                p += (nh->n_descsz + 3) & ~3u;
                if (p > end)
                    break;
                if (nh->n_type == NT_GNU_BUILD_ID && nh->n_namesz == 4 &&
                    !memcmp(reinterpret_cast<void *>(np), "GNU", 4)) {
                    char hex[3];
                    for (uint32_t j = 0; j < nh->n_descsz; j++) {
                        snprintf(hex, sizeof(hex), "%02x", *reinterpret_cast<uint8_t *>(dp + j));
                        engine.buildId += hex;
                    }
                }
            }
        }
    }
    const ElfW(Sym) *symbols = nullptr;
    const char *strings = nullptr;
    const ElfW(Rela) *rel = nullptr;
    size_t relSize = 0;
    const ElfW(Rela) *jmp = nullptr;
    size_t jmpSize = 0;
    // Android keeps dynamic pointers relative to load bias in the ELF image.
    auto absolute = [&](uintptr_t p) { return p < engine.base ? engine.base + p : p; };
    if (!dynamic)
        return 1;
    for (auto d = dynamic; d->d_tag != DT_NULL; d++)
        switch (d->d_tag) {
        case DT_SYMTAB:
            symbols = reinterpret_cast<const ElfW(Sym) *>(absolute(d->d_un.d_ptr));
            break;
        case DT_STRTAB:
            strings = reinterpret_cast<const char *>(absolute(d->d_un.d_ptr));
            break;
        case DT_RELA:
            rel = reinterpret_cast<const ElfW(Rela) *>(absolute(d->d_un.d_ptr));
            break;
        case DT_RELASZ:
            relSize = d->d_un.d_val;
            break;
        case DT_JMPREL:
            jmp = reinterpret_cast<const ElfW(Rela) *>(absolute(d->d_un.d_ptr));
            break;
        case DT_PLTRELSZ:
            jmpSize = d->d_un.d_val;
            break;
        }
    if (!symbols || !strings)
        return 1;
    auto gather = [&](const ElfW(Rela) * records, size_t bytes) {
        if (!records)
            return;
        for (size_t i = 0; i < bytes / sizeof(*records); i++) {
            size_t idx = ELF64_R_SYM(records[i].r_info);
            unsigned type = ELF64_R_TYPE(records[i].r_info);
#if defined(__aarch64__)
            bool pointerRelocation = type == R_AARCH64_JUMP_SLOT || type == R_AARCH64_GLOB_DAT;
            bool absoluteFunction = type == R_AARCH64_ABS64;
#elif defined(__x86_64__)
            bool pointerRelocation = type == R_X86_64_JUMP_SLOT || type == R_X86_64_GLOB_DAT;
            bool absoluteFunction = type == R_X86_64_64;
#else
            bool pointerRelocation = false;
            bool absoluteFunction = false;
#endif
            if (idx && pointerRelocation)
                slots[strings + symbols[idx].st_name].push_back(
                    reinterpret_cast<void **>(engine.base + records[i].r_offset));
            if (idx && absoluteFunction && records[i].r_addend == 0 &&
                ELF64_ST_TYPE(symbols[idx].st_info) == STT_FUNC)
                directFunctionSlots[strings + symbols[idx].st_name].push_back(
                    reinterpret_cast<void **>(engine.base + records[i].r_offset));
        }
    };
    gather(rel, relSize);
    gather(jmp, jmpSize);
    return 1;
}
} // namespace
bool Engine::load() {
    library = dlopen("libsmashhit.so", RTLD_NOW | RTLD_NOLOAD);
    if (!library) {
        error = "Original native library is not loaded";
        return false;
    }
    dl_iterate_phdr(inspect, nullptr);
#if defined(__x86_64__)
    const char *expected = "ac3b897010a22367c4829bf6429e90e74f5b0fce";
#elif defined(__aarch64__)
    const char *expected = "9a19cf78b221d208df133b8ca6001b78c65480bd";
#else
    error = "Developer tools require arm64-v8a or x86_64";
    return false;
#endif
    if (buildId != expected) {
        error = "Unsupported game build ID: " + buildId;
        return false;
    }
#define LOAD(member, name)                                                                         \
    member = reinterpret_cast<decltype(member)>(dlsym(library, name));                             \
    if (!member) {                                                                                 \
        error = "Missing native symbol " name;                                                     \
        return false;                                                                              \
    }
    LOAD(globalGame, "gGame");
    LOAD(gameFrame, "_ZN4Game5frameEv");
    LOAD(gameDraw, "_ZN4Game4drawEv");
    LOAD(gameUpdate, "_ZN4Game6updateEv");
    LOAD(gameSetState, "_ZN4Game8setStateE9GameStateb");
    LOAD(gameStartLevel, "_ZN4Game10startLevelEv");
    LOAD(gameStopLevel, "_ZN4Game9stopLevelEv");
    LOAD(gameSetPaused, "_ZN4Game9setPausedEb");
    LOAD(gameUpdateTutorial, "_ZN4Game14updateTutorialEv");
    LOAD(tutorialCheckTriggers, "_ZN13TutorialUtils21checkTutorialTriggersER15TutorialManagerRK14Qi"
                                "ArrayInplaceI11ObstacleDefLi64EERK6Playerf");
    LOAD(tutorialId, "_ZNK15TutorialManager20getCurrentTutorialIdEv");
    LOAD(sceneDraw, "_ZN5Scene4drawEv");
    LOAD(levelUpdate, "_ZN5Level6updateEv");
    LOAD(levelStart, "_ZN5Level5startEv");
    LOAD(levelStop, "_ZN5Level4stopEv");
    LOAD(levelReset, "_ZN5Level5resetEb");
    LOAD(levelInput, "_ZN5Level11handleInputERK7QiInput");
    LOAD(levelClassicBall, "_ZN5Level17createClassicBallEi");
    LOAD(levelCenter, "_ZN5Level12centerCameraEv");
    LOAD(levelDestroy, "_ZN5Level7destroyEP6Entity");
    LOAD(levelHit, "_ZN5Level12hitSomethingEi");
    LOAD(levelGameOver, "_ZN5Level15TriggerGameOverEv");
    LOAD(physicsRemoveBody, "_ZN7Physics6removeEP4Body");
    LOAD(physicsUpdate, "_ZN7Physics6updateEv");
    LOAD(bodyUpdate, "_ZN4Body6updateEv");
    LOAD(bodyBounds, "_ZN4Body13computeBoundsEv");
    LOAD(playerQuickSave, "_ZN6Player9quickSaveEv");
    LOAD(playerQuickLoad, "_ZN6Player9quickLoadEv");
    LOAD(playerHighScore, "_ZN6Player12getHighScoreEi");
    LOAD(playerCheckpointCount, "_ZN6Player18getCheckpointCountEv");
    LOAD(playerLoadCheckpoint, "_ZN6Player14loadCheckpointEi");
    LOAD(levelLoadNext, "_ZN5Level12loadNextRoomEv");
    LOAD(roomDraw, "_ZN4Room4drawEv");
    LOAD(roomDestructor, "_ZN4RoomD2Ev");
    LOAD(roomGetProgress, "_ZNK4Room11getProgressEv");
    LOAD(roomConstructor, "_ZN4RoomC2EP5LevelRK8QiStringRK7QiArrayI9ParameterEf");
    LOAD(obstacleDestructor, "_ZN8ObstacleD2Ev");
    LOAD(obstacleUpdate, "_ZN8Obstacle6updateEv");
    LOAD(batchLoad, "_ZN11RenderBatch4loadEv");
    LOAD(roomCreateSegment, "_ZN4Room13createSegmentERK8QiStringf");
    LOAD(roomCreateObstacle,
         "_ZN4Room14createObstacleERK8QiStringRK12QiTransform3RK7QiArrayI9ParameterE");
    LOAD(bodyTransform, "_ZN4Body12setTransformERK12QiTransform3");
    LOAD(bodyMass, "_ZN4Body21computeMassPropertiesEv");
    LOAD(polyNormals, "_ZN10Polyhedron14computeNormalsEb");
    LOAD(viewportPosition, "_ZN10QiViewport12setCameraPosERK6QiVec3");
    LOAD(viewportRotation, "_ZN10QiViewport12setCameraRotERK6QiQuat");
    LOAD(viewportMode, "_ZN10QiViewport9setMode3DEfff");
    LOAD(vboUpload, "_ZN14QiVertexBuffer7makeVboEv");
    LOAD(drawTriangles,
         "_ZN10QiRenderer13drawTrianglesERK9QiMatrix4PK14QiVertexBufferPK13QiIndexBufferii");
    LOAD(raycast, "_ZN5Level7raycastERK6QiVec3S2_iPS0_S3_PP5ShapeP8Obstacle");
    LOAD(stringCtor, "_ZN8QiStringC2EPKc");
    LOAD(stringAssign, "_ZN8QiStringaSEPKc");
    LOAD(stringDtor, "_ZN8QiStringD2Ev");
    LOAD(gameRestart, "_ZN4Game12RestartLevelE8QiString");
    LOAD(musicLocation, "_ZN5Audio21getLevelMusicLocationEv");
#undef LOAD
    return true;
}
bool Engine::hasHook(const char *name, bool directFunctions) const {
    auto i = slots.find(name);
    if (i == slots.end() || i->second.empty()) return false;
    auto d = directFunctionSlots.find(name);
    return !directFunctions || (d != directFunctionSlots.end() && !d->second.empty());
}
bool Engine::hook(const char *name, void *replacement, bool directFunctions) {
    auto found = slots.find(name);
    if (!hasHook(name, directFunctions)) {
        error = "No relocation slot for " + std::string(name);
        return false;
    }
    auto targets = found->second;
    if (directFunctions) {
        const auto &extra = directFunctionSlots.at(name);
        targets.insert(targets.end(), extra.begin(), extra.end());
    }
    const auto page = static_cast<uintptr_t>(sysconf(_SC_PAGESIZE));
    for (void **slot : targets) {
        void *p = reinterpret_cast<void *>(reinterpret_cast<uintptr_t>(slot) & ~(page - 1));
        if (mprotect(p, page, PROT_READ | PROT_WRITE)) {
            error = "Unable to write relocation page";
            return false;
        }
        __atomic_store_n(slot, replacement, __ATOMIC_RELEASE);
        mprotect(p, page, PROT_READ);
    }
    return true;
}
} // namespace shdev
