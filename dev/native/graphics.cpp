#include "state.hpp"
#include "play.hpp"
#include <GLES2/gl2.h>
#include <dlfcn.h>
#include <map>

namespace shdev {
namespace {
decltype(&glShaderSource) originalSource;
decltype(&glUseProgram) originalUse;
decltype(&glEnable) originalEnable;
decltype(&glLinkProgram) originalLink;
std::map<GLuint, GLint> uniforms;
uint64_t changedShaders = 0, fogWrites = 0;
float lastFogValue = -1;
GLuint lastFogProgram = 0;
uint64_t lastFogFrame = uint64_t(-1);
void sourceHook(GLuint shader, GLsizei count, const GLchar *const *strings, const GLint *lengths) {
    std::string code;
    for (int i = 0; i < count; i++)
        if (strings[i])
            code.append(strings[i], lengths && lengths[i] >= 0 ? static_cast<size_t>(lengths[i])
                                                               : strlen(strings[i]));
    // This exact expression is present in shipped shaders. Preserve its normal
    // value with a uniform default of zero. Play and tools have separate settings.
    const std::string needle = "float fog = clamp(0.05 * (-5.0 + gl_Position.z), 0.0, 1.0);";
    size_t at = 0;
    bool changed = false;
    while ((at = code.find(needle, at)) != std::string::npos) {
        const std::string replacement =
            "float fog = (1.0-uShdevNoFog)*clamp(0.05 * (-5.0 + gl_Position.z), 0.0, 1.0);";
        code.replace(at, needle.size(), replacement);
        at += replacement.size();
        changed = true;
    }
    if (!changed) {
        originalSource(shader, count, strings, lengths);
        return;
    }
    ++changedShaders;
    size_t insert = 0;
    if (code.rfind("#version", 0) == 0) {
        insert = code.find('\n');
        insert = insert == std::string::npos ? code.size() : insert + 1;
    }
    code.insert(insert, "uniform mediump float uShdevNoFog;\n");
    const char *text = code.c_str();
    GLint length = code.size();
    originalSource(shader, 1, &text, &length);
}
void useHook(GLuint program) {
    originalUse(program);
    if (!program)
        return;
    auto it = uniforms.find(program);
    if (it == uniforms.end())
        it = uniforms.emplace(program, glGetUniformLocation(program, "uShdevNoFog")).first;
    if (it->second >= 0) {
        glUniform1f(it->second, play.fogHidden() ? 1.f : 0.f);
        if (lastFogFrame != state.frame) {
            glGetUniformfv(program, it->second, &lastFogValue);
            lastFogProgram = program; lastFogFrame = state.frame;
        }
        ++fogWrites;
    }
}
void enableHook(GLenum cap) {
    if (cap == GL_CULL_FACE && state.renderOverride && state.twoSided) {
        glDisable(GL_CULL_FACE);
        return;
    }
    originalEnable(cap);
}
void linkHook(GLuint program) {
    originalLink(program);
    uniforms.erase(program);
}
} // namespace
Json graphicsInfo() {
    return {{"patched_shaders", changedShaders}, {"fog_uniform_writes", fogWrites},
            {"last_fog_uniform", lastFogValue}, {"last_fog_program", lastFogProgram}, {"last_fog_frame", lastFogFrame}};
}
bool installGraphics() {
    originalSource =
        reinterpret_cast<decltype(originalSource)>(dlsym(engine.library, "glShaderSource"));
    originalUse = reinterpret_cast<decltype(originalUse)>(dlsym(engine.library, "glUseProgram"));
    originalEnable = reinterpret_cast<decltype(originalEnable)>(dlsym(engine.library, "glEnable"));
    originalLink = reinterpret_cast<decltype(originalLink)>(dlsym(engine.library, "glLinkProgram"));
    if (!originalSource || !originalUse || !originalEnable || !originalLink)
        return false;
    if (!engine.hasHook("glShaderSource") || !engine.hasHook("glUseProgram") ||
        !engine.hasHook("glEnable") || !engine.hasHook("glLinkProgram"))
        return false;
    return engine.hook("glShaderSource", reinterpret_cast<void *>(sourceHook)) &&
           engine.hook("glUseProgram", reinterpret_cast<void *>(useHook)) &&
           engine.hook("glEnable", reinterpret_cast<void *>(enableHook)) &&
           engine.hook("glLinkProgram", reinterpret_cast<void *>(linkHook));
}
} // namespace shdev
