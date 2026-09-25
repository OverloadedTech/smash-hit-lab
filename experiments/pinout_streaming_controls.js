/* Experimental mutations, appended only by verify_pinout_streaming.py after
 * the build-checked observer. This is not part of the read-only recorder.
 * Commands execute on Game::frame. Original streaming and table code runs.
 * Physics may be held so that ball/camera position can be varied independently.
 */
'use strict';
if (globalThis.pinoutStreamingExperiment !== true) throw new Error('Explicit experiment mode required');

const commands = [];
let holdBall = null, cameraWorld = null, lookBack = false, freezePhysics = false;
let physicsCalls = 0, physicsHeld = 0, savedPose = null, response = null;
const transformBuffer = Memory.alloc(28);
const setBodyTransform = new NativeFunction(sym('_ZN4Body13setTransform3ERK12QiTransform3'),
                                           'void', ['pointer', 'pointer']);
const physicsAddress = sym('_ZN7Physics6updateEv');
const originalPhysics = new NativeFunction(physicsAddress, 'void', ['pointer']);

function writeVector(p, values) { values.forEach((v, i) => p.add(4 * i).writeFloat(v)); }
function checkedVector(values) {
    if (!Array.isArray(values) || values.length !== 3 ||
        values.some(v => !Number.isFinite(v) || Math.abs(v) > 10000))
        throw new Error('Expected three finite coordinates in laboratory range');
    return values.slice();
}
function controlsState() {
    return {hold_ball_world: holdBall, camera_world: cameraWorld,
            look_back: lookBack, physics_frozen: freezePhysics, physics_calls: physicsCalls,
            physics_held: physicsHeld};
}
function placeBall(g, l, position, rotation = null) {
    const ball = l.add(0x108).readPointer();
    if (ball.isNull()) throw new Error('No ball');
    transformBuffer.writeByteArray(ball.add(0x158).readByteArray(28));
    writeVector(transformBuffer, [position[0], position[1] - l.add(0x314).readFloat(), position[2]]);
    if (rotation) writeVector(transformBuffer.add(12), rotation);
    setBodyTransform(ball, transformBuffer);
    writeVector(ball.add(0x174), [0, 0, 0, 0, 0, 0]);
}

Interceptor.replace(physicsAddress, new NativeCallback(function (p) {
    if (freezePhysics) { ++physicsHeld; return; }
    ++physicsCalls;
    originalPhysics(p);
}, 'void', ['pointer']));

Interceptor.attach(sym('_ZN4Game5frameEv'), {
    onEnter(args) {
        const g = args[0], l = g.add(0x40).readPointer();
        for (const cmd of commands.splice(0)) {
            try {
                if (cmd.op === 'release') {
                    holdBall = null; cameraWorld = null; lookBack = false; freezePhysics = false;
                    response = cmd;
                    emit('experiment_command', {command: cmd, controls: controlsState()});
                    continue;
                }
                if (g.add(0x180).readS32() !== 2 || l.isNull()) throw new Error('Original run must be active');
                const s = snapshot();
                if (cmd.op === 'hold_here') {
                    if (!savedPose) savedPose = {
                        level: l.toString(), world: [s.ball.position[0], s.ball.position[1] + s.origin_y, s.ball.position[2]],
                        rotation: Array.from({length: 4}, (_, i) =>
                            l.add(0x108).readPointer().add(0x164 + 4 * i).readFloat())
                    };
                    holdBall = [s.ball.position[0], s.ball.position[1] + s.origin_y, s.ball.position[2]];
                    freezePhysics = true;
                } else if (cmd.op === 'ball_world') {
                    holdBall = checkedVector(cmd.position);
                } else if (cmd.op === 'table') {
                    const t = s.tables[cmd.index];
                    if (!Number.isInteger(cmd.index) || !t) throw new Error('Unknown table index');
                    holdBall = [0, s.origin_y + t.offset_y + t.length * 0.5, 0.05];
                } else if (cmd.op === 'camera_world') {
                    cameraWorld = cmd.position === null ? null : checkedVector(cmd.position);
                } else if (cmd.op === 'look_back') {
                    lookBack = !!cmd.value;
                } else if (cmd.op === 'restore') {
                    if (!savedPose || savedPose.level !== l.toString()) throw new Error('Saved Level no longer exists');
                    holdBall = savedPose.world.slice(); cameraWorld = null; lookBack = false; freezePhysics = true;
                    placeBall(g, l, holdBall, savedPose.rotation);
                } else if (cmd.op === 'release') {
                    holdBall = null; cameraWorld = null; lookBack = false; freezePhysics = false;
                } else if (cmd.op !== 'sample') throw new Error('Unknown operation');
                response = cmd;
                emit('experiment_command', {command: cmd, controls: controlsState()});
            } catch (error) {
                emit('experiment_error', {command: cmd, error: String(error)});
            }
        }
        if (holdBall && !l.isNull() && g.add(0x180).readS32() === 2)
            safe(() => placeBall(g, l, holdBall));
    },
    onLeave() {
        if (response) {
            const cmd = response; response = null;
            safe(() => emit('experiment_result', {id: cmd.id, controls: controlsState(), snapshot: snapshot()}));
        }
    }
});

Interceptor.attach(sym('_ZN6Camera6updateEv'), {
    onLeave() {
        if (!cameraWorld && !lookBack) return;
        safe(() => {
            const g = gameGlobal.readPointer(), l = g.add(0x40).readPointer();
            const display = g.add(0x10).readPointer();
            if (cameraWorld) {
                const position = [cameraWorld[0], cameraWorld[1] - l.add(0x314).readFloat(), cameraWorld[2]];
                writeVector(l.add(0x308).readPointer().add(0x10), position);
                writeVector(display.add(0xa50), position);
            }
            if (lookBack) {
                const q = Array.from({length: 4}, (_, i) => display.add(0xa5c + 4 * i).readFloat());
                // Premultiply by a half-turn about PinOut's world Z/up axis.
                writeVector(display.add(0xa5c), [-q[1], q[0], q[3], -q[2]]);
            }
        });
    }
});

rpc.exports.command = command => { commands.push(command); return {queued: true}; };
emit('streaming_controls_ready', {mutations_enabled: true,
     scope: 'Reversible ball pose/camera overrides and Physics::update hold; original Level::tick and Table lifecycle unchanged.'});
