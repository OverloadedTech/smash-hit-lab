#include "state.hpp"
#include <android/asset_manager_jni.h>
#include <jni.h>

using namespace shdev;
extern "C" JNIEXPORT jstring JNICALL
Java_dev_smashhit_DevBridge_init(JNIEnv *env, jclass, jobject assets, jstring path) {
    const char *p = env->GetStringUTFChars(path, nullptr);
    bool ok = install(AAssetManager_fromJava(env, assets), p);
    env->ReleaseStringUTFChars(path, p);
    return env->NewStringUTF(ok ? "" : state.error.c_str());
}
extern "C" JNIEXPORT void JNICALL Java_dev_smashhit_DevBridge_command(JNIEnv *env, jclass,
                                                                      jstring text) {
    const char *p = env->GetStringUTFChars(text, nullptr);
    queue(p);
    env->ReleaseStringUTFChars(text, p);
}
extern "C" JNIEXPORT jstring JNICALL Java_dev_smashhit_DevBridge_snapshot(JNIEnv *env, jclass) {
    std::string s = published();
    return env->NewStringUTF(s.c_str());
}
extern "C" JNIEXPORT jlong JNICALL Java_dev_smashhit_DevBridge_shotSerial(JNIEnv *, jclass) {
    return static_cast<jlong>(state.shotSerial.load(std::memory_order_acquire));
}
