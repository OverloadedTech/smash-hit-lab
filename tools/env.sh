#!/usr/bin/env bash
# Source this file to use the workspace-local tools.
SH_WORKSPACE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SH_JAVA_DIR=("$SH_WORKSPACE"/tools/jdk/jdk-*)
export JAVA_HOME="${SH_JAVA_DIR[0]}"
export ANDROID_SDK_ROOT="$SH_WORKSPACE/tools/sdk"
export ANDROID_AVD_HOME="$SH_WORKSPACE/build/avd"
export PATH="$JAVA_HOME/bin:$ANDROID_SDK_ROOT/platform-tools:$SH_WORKSPACE/tools/venv/bin:$PATH"
