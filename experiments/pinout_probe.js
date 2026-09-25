/* Read-only lifecycle probe for the supplied PinOut 1.0.7 x86_64 library.
 * This is a research instrument, not an in-game developer addon.
 * All field reads happen on original Game/Level callbacks. No game fields,
 * saves, entitlement flags, assets or native return values are changed.
 */
'use strict';

const module = Process.getModuleByName('libpinout.so');
const expectedBuildId = 'eff8efba16b53a2a60f5abae5f485ee8a3edf17e';

function buildId(m) {
    const base = m.base;
    if (base.readU32() !== 0x464c457f || base.add(4).readU8() !== 2 ||
        base.add(5).readU8() !== 1) throw new Error('Expected ELF64 little endian');
    const phoff = base.add(32).readU64().toNumber();
    const stride = base.add(54).readU16(), count = base.add(56).readU16();
    if (stride !== 56 || count > 64 || phoff > 65536) throw new Error('Unexpected ELF header');
    for (let i = 0; i < count; ++i) {
        const ph = base.add(phoff + i * stride);
        if (ph.readU32() !== 4) continue;
        const address = ph.add(16).readU64().toNumber();
        const size = ph.add(32).readU64().toNumber();
        if (size > 65536) throw new Error('Unexpected ELF notes size');
        for (let offset = 0; offset + 12 <= size;) {
            const note = base.add(address + offset);
            const nameSize = note.readU32(), descSize = note.add(4).readU32();
            const nameAligned = Math.ceil(nameSize / 4) * 4;
            const descAligned = Math.ceil(descSize / 4) * 4;
            const length = 12 + nameAligned + descAligned;
            if (offset + length > size) throw new Error('Invalid ELF note');
            if (note.add(8).readU32() === 3 && nameSize === 4 &&
                note.add(12).readU32() === 0x00554e47) {
                return Array.from(new Uint8Array(note.add(12 + nameAligned).readByteArray(descSize)),
                                  b => b.toString(16).padStart(2, '0')).join('');
            }
            offset += length;
        }
    }
    throw new Error('GNU build ID absent');
}

const observedBuildId = buildId(module);
if (Process.arch !== 'x64' || observedBuildId !== expectedBuildId)
    throw new Error('Unsupported PinOut build: ' + Process.arch + ' / ' + observedBuildId);

const sym = name => module.getExportByName(name);
const gameGlobal = sym('gGame');
let frame = 0, tick = 0, lastSample = 0, errors = 0, cached = null;
const vec = p => [p.readFloat(), p.add(4).readFloat(), p.add(8).readFloat()];

function qiString(p) {
    const heap = p.readPointer();
    const text = (heap.isNull() ? p.add(16) : heap).readUtf8String();
    if (text.length > 1024) throw new Error('Unexpected QiString length');
    return text;
}

function array(p, countOffset, dataOffset, limit = 512) {
    const count = p.add(countOffset).readS32(), data = p.add(dataOffset).readPointer();
    if (count < 0 || count > limit || (count && data.isNull()))
        throw new Error('Invalid array at ' + p.add(countOffset));
    return Array.from({length: count}, (_, i) => data.add(8 * i).readPointer());
}

function table(p) {
    if (p.isNull()) return null;
    const retained = p.add(0x340).readPointer();
    const bodies = array(p, 0xf0, 0xf8, 10000);
    return {
        address: p.toString(), name: qiString(p.add(0x140)),
        offset_y: p.add(0x170).readFloat(), length: p.add(0x178).readFloat(),
        checkpoint: p.add(0x17c).readS32(), active: p.add(0x2a8).readU8() !== 0,
        preload_stage: p.add(0x350).readS32(),
        entities: p.add(0xe0).readS32(), bodies: bodies.length,
        retained_table_body: retained.toString(),
        streamed_bodies: bodies.filter(body => !body.equals(retained)).length,
        shared_render_vertices: p.add(0x1a0).readS32()
    };
}

function snapshot() {
    const g = gameGlobal.readPointer();
    if (g.isNull()) return {game: null};
    const l = g.add(0x40).readPointer();
    if (l.isNull()) return {game: g.toString(), level: null};
    const ball = l.add(0x108).readPointer(), camera = l.add(0x308).readPointer();
    const current = l.add(0x120).readPointer();
    const tables = array(l, 0x128, 0x130).map((p, i) => ({index: i, ...table(p)}));
    return {
        game: g.toString(), level: l.toString(), game_state: g.add(0x180).readS32(),
        native_paused: g.add(0x1f0).readU8() !== 0,
        native_dt: g.add(0x150).readFloat(),
        ball: ball.isNull() ? null : {
            address: ball.toString(), position: vec(ball.add(0x158)),
            velocity: vec(ball.add(0x174)), angular_velocity: vec(ball.add(0x180))
        },
        camera: camera.isNull() ? null : {
            address: camera.toString(), position: vec(camera.add(0x10))
        },
        render_camera_position: vec(g.add(0x10).readPointer().add(0xa50)),
        render_camera_rotation: Array.from({length: 4}, (_, i) =>
            g.add(0x10).readPointer().add(0xa5c + 4 * i).readFloat()),
        origin_y: l.add(0x314).readFloat(), distance: l.add(0x318).readFloat(),
        current_table: tables.find(t => t.address === current.toString()) || null,
        active_tables: array(l, 0x138, 0x140).map(p => p.toString()), tables
    };
}

function emit(event, data = {}) { send({event, time_ms: Date.now(), frame, tick, ...data}); }
function safe(fn) {
    if (errors >= 10) return;
    try { fn(); } catch (error) {
        ++errors; emit('read_error', {error: String(error), errors});
    }
}
function sample(force = false) {
    const now = Date.now();
    if (!force && now - lastSample < 1000) return;
    lastSample = now;
    safe(() => { cached = snapshot(); emit('sample', {snapshot: cached}); });
}

Interceptor.attach(sym('_ZN4Game5frameEv'), {
    onEnter() { ++frame; },
    onLeave() { sample(); }
});
Interceptor.attach(sym('_ZN5Level4tickEv'), {
    onEnter() { ++tick; }
});

for (const [name, symbol] of [
    ['table_load', '_ZN5Table4loadER13QiInputStreami'],
    ['table_activate', '_ZN5Table8activateEv'],
    ['table_deactivate', '_ZN5Table10deactivateEv'],
    ['table_deload', '_ZN5Table6deloadEv'],
    ['table_load_bodies', '_ZN5Table10loadBodiesEv'],
    ['table_unload_bodies', '_ZN5Table12unloadBodiesEv']
]) {
    Interceptor.attach(sym(symbol), {
        onEnter(args) {
            this.p = args[0];
            if (name !== 'table_load') safe(() => { this.before = table(this.p); });
        },
        onLeave() { safe(() => emit(name, {before: this.before || null, after: table(this.p)})); }
    });
}
Interceptor.attach(sym('_ZN5Table7preloadEv'), {
    onEnter(args) { this.p = args[0]; this.start = this.p.add(0x350).readS32(); },
    onLeave() {
        if ([0, 1, 2, 3, 10, 90, 91, 92, 93, 94, 99].includes(this.start))
            safe(() => emit('table_preload', {before_stage: this.start, after: table(this.p)}));
    }
});
Interceptor.attach(sym('_ZN5TableD2Ev'), {
    onEnter(args) { safe(() => emit('table_destroy', {table: table(args[0])})); }
});
Interceptor.attach(sym('_ZN5Level10enterTableEP5Table'), {
    onEnter(args) {
        this.l = args[0]; this.p = args[1];
        safe(() => { this.before = snapshot(); });
    },
    onLeave() {
        safe(() => emit('enter_table', {before: this.before, after: snapshot(), entered: table(this.p)}));
    }
});

rpc.exports = { latest() { return cached; } };
emit('probe_ready', {module: module.name, base: module.base.toString(),
                     arch: Process.arch, build_id: observedBuildId,
                     read_only: globalThis.pinoutStreamingExperiment !== true});
