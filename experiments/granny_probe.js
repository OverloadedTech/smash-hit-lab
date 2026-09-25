/* Read-only, exported-function observation for Granny Smith 1.3.8 ARMv7.
 * The host verifies the actual mapped library bytes before this script loads.
 * No internal object offsets, fields, saves or native return values are changed.
 */
'use strict';
const expectedGrannyLibrary = 'ab1fd12d06952937aa802c3a4e6a4e2c413a20ebfa51a95ca33ca5cd75f788f1';
if (Process.arch !== 'arm' || globalThis.grannyVerifiedLibrarySha !== expectedGrannyLibrary)
    throw new Error('Host must verify the supplied ARMv7 library before attaching');
const grannyModule = Process.getModuleByName('libgrannysmith.so');
let grannyFrames = 0, box2dSteps = 0, entityCreates = 0, entityDestroys = 0;
let lastGrannySample = 0, lastStep = null;
const seenWorlds = new Set(), entityTypes = {};
const floatWord = word => {
    const bytes = new ArrayBuffer(4), view = new DataView(bytes);
    view.setUint32(0, word, true); return view.getFloat32(0, true);
};
const grannyEmit = (event, data = {}) => send({event, time_ms: Date.now(),
    frames: grannyFrames, box2d_steps: box2dSteps, ...data});

Interceptor.attach(grannyModule.getExportByName('_ZN7b2World4StepEfii'), {
    onEnter(args) {
        ++box2dSteps;
        // Android armeabi-v7a uses softfp procedure-call conventions: the float
        // dt occupies the second core argument slot. Its observed values and
        // both iteration arguments are checked by the host report.
        lastStep = {world: args[0].toString(), dt: floatWord(args[1].toUInt32()),
                    velocity_iterations: args[2].toInt32(), position_iterations: args[3].toInt32()};
        if (!Number.isFinite(lastStep.dt)) throw new Error('Nonfinite Box2D dt; ABI check failed');
        if (!seenWorlds.has(lastStep.world)) {
            seenWorlds.add(lastStep.world); grannyEmit('box2d_world_observed', lastStep);
        }
    }
});
Interceptor.attach(grannyModule.getExportByName('_ZN4Game5frameEv'), {
    onEnter() { ++grannyFrames; },
    onLeave() {
        const now = Date.now();
        if (now - lastGrannySample < 1000) return;
        lastGrannySample = now;
        grannyEmit('sample', {last_step: lastStep, observed_world_addresses: seenWorlds.size,
            entity_creates_since_attach: entityCreates, entity_destroy_calls_since_attach: entityDestroys,
            created_entity_type_numbers: entityTypes});
    }
});
Interceptor.attach(grannyModule.getExportByName('_ZN5Level12createEntityEN6Entity4TypeE'), {
    onEnter(args) {
        ++entityCreates;
        const type = String(args[1].toInt32());
        entityTypes[type] = (entityTypes[type] || 0) + 1;
    }
});
Interceptor.attach(grannyModule.getExportByName('_ZN5Level7destroyEP6Entity'), {
    onEnter() { ++entityDestroys; }
});
Interceptor.attach(grannyModule.getExportByName('_ZN5Level4loadER13QiInputStreamib'), {
    onEnter(args) {
        this.level = args[0].toString(); this.before = entityCreates;
        this.bytes = args[2].toInt32(); this.init = args[3].toInt32() !== 0;
        grannyEmit('level_load_begin', {level: this.level, input_bytes: this.bytes, initialize: this.init});
    },
    onLeave() { grannyEmit('level_load_end', {level: this.level, observed_entity_creates: entityCreates - this.before}); }
});
for (const [event, name] of [
    ['game_start_level', '_ZN4Game10startLevelEv'],
    ['load_attract_level', '_ZN4Game16loadAttractLevelEb'],
    ['level_clear', '_ZN5Level5clearEv']
]) {
    Interceptor.attach(grannyModule.getExportByName(name), {
        onEnter(args) { grannyEmit(event, {instance: args[0].toString()}); }
    });
}
grannyEmit('probe_ready', {arch: Process.arch, module: grannyModule.name,
    base: grannyModule.base.toString(), verified_library_sha256: expectedGrannyLibrary, read_only: true});
