#include "editor.hpp"
#include "play.hpp"
#include "storage.hpp"
#include <sstream>

namespace shdev {
namespace {
constexpr size_t recordLimit = 8192;
constexpr const char *gameInput = "3b2ffa02fee8ca762f40648f1a9bec5c308764e881dd6a79cacd6dccdb16e338";
bool same(const Json &a, const Json &b) {
    if (a.is_number() && b.is_number()) return std::abs(a.get<double>() - b.get<double>()) < 1e-5;
    if (a.type() != b.type() || a.size() != b.size()) return false;
    if (a.is_object()) {
        for (auto it = a.begin(); it != a.end(); ++it)
            if (!b.contains(it.key()) || !same(it.value(), b.at(it.key()))) return false;
        return true;
    }
    if (a.is_array()) {
        for (size_t i = 0; i < a.size(); ++i) if (!same(a[i], b[i])) return false;
        return true;
    }
    return a == b;
}
Quat rotation(const Json &value) {
    if (!value.is_array() || value.size() != 4) throw std::runtime_error("Invalid saved rotation");
    Quat q{value[0].get<float>(), value[1].get<float>(), value[2].get<float>(), value[3].get<float>()};
    float size = q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w;
    if (!std::isfinite(size) || size < .0001f || size > 100) throw std::runtime_error("Invalid saved rotation");
    return q.normalized();
}
Vec3 savedVector(const Json &value) {
    if (!value.is_array() || value.size() != 3) throw std::runtime_error("Invalid saved coordinates");
    Vec3 v = vec(value);
    if (std::max({std::abs(v.x), std::abs(v.y), std::abs(v.z)}) > 1e7f)
        throw std::runtime_error("Saved coordinates are outside the supported range");
    return v;
}
Json geometrySignature(const BodyEdit &b) {
    // Shape order is the native construction order, never a serialized address.
    Json shapes = Json::array();
    for (void *shape : array(b.body, off::bodyShapes)) {
        const auto &vertices = b.originalPoly.at(shape);
        uint64_t hash = 1469598103934665603ull;
        for (Vec3 v : vertices) {
            // Quantization tolerates harmless floating point construction noise.
            for (float f : {v.x, v.y, v.z}) {
                int64_t n = std::llround(f * 10000);
                for (unsigned i = 0; i < 8; ++i) { hash ^= (uint64_t(n) >> (i*8)) & 255; hash *= 1099511628211ull; }
            }
        }
        shapes.push_back({{"vertices", vertices.size()}, {"geometry", std::to_string(hash)}});
    }
    return shapes;
}
Json fileData(const Json &records) {
    return {{"version", 1}, {"input_sha256", gameInput}, {"records", records}};
}
}
Json Editor::segmentTarget(const Segment &s) {
    return {{"room", qiString(at(s.room, off::roomName))}, {"source", s.source}, {"occurrence", s.occurrence}};
}
Transform Editor::originalBodyPose(const BodyEdit &b) {
    if (!b.sourceRoom) return {state.local(b.originalWorld), b.original.rotation};
    Transform room = read<Transform>(ptr(b.sourceRoom, off::roomBody), off::entityTransform);
    Vec3 p = b.sourceOriginal.position; p.z += b.sourceOffset;
    return {room.position + room.rotation.rotate(p), room.rotation * b.sourceOriginal.rotation};
}
Json Editor::savedRecord(Selection target) {
    if (target.kind == Selection::Box) {
        const auto &s = segments.at(target.target);
        const auto &b = s.boxes.at(target.box);
        Json identity = segmentTarget(s);
        identity["kind"] = "box"; identity["source_index"] = b.sourceIndex; identity["box"] = b.ordinal;
        Vec3 position = b.position, center = b.center;
        position.z -= s.offset; center.z -= s.offset;
        return {{"target", identity}, {"baseline", {{"center", jvec(center)}, {"half", jvec(b.half)},
            {"vertices", b.vertices.size()}, {"mesh_vertices", s.expectedVertices}}},
            {"position", jvec(position)}, {"rotation", jquat(b.rotation)}, {"scale", jvec(b.scale)}};
    }
    if (target.kind != Selection::Body) return nullptr;
    const auto &b = bodies.at(target.target);
    if (b.sourceTarget.is_null()) return nullptr;
    Transform room = read<Transform>(ptr(b.sourceRoom, off::roomBody), off::entityTransform);
    Transform actual = read<Transform>(b.body, off::entityTransform);
    Vec3 local = room.rotation.inverse().rotate(actual.position - room.position); local.z -= b.sourceOffset;
    return {{"target", b.sourceTarget}, {"baseline", geometrySignature(b)},
        {"position", jvec(local)}, {"rotation", jquat(room.rotation.inverse() * actual.rotation)}, {"scale", jvec(b.scale)}};
}
void Editor::loadSaved() {
    try {
        Json data = readLocalJson(state.files + "/level-edits.json", 16 * 1024 * 1024);
        if (data.is_null()) return;
        if (data.at("version") != 1 || data.at("input_sha256") != gameInput)
            throw std::runtime_error("Saved edits belong to a different game or format");
        Json records = data.at("records");
        if (!records.is_object() || records.size() > recordLimit) throw std::runtime_error("Invalid saved edit list");
        for (auto it = records.begin(); it != records.end(); ++it) {
            const auto &record = it.value();
            if (record.at("target").dump() != it.key()) throw std::runtime_error("Saved object identity does not match");
            savedVector(record.at("position")); savedVector(record.at("scale")); rotation(record.at("rotation"));
        }
        savedRecords = std::move(records);
        event("saved_edits_loaded", {{"count", savedRecords.size()}});
    } catch (const std::exception &error) {
        savedError = error.what();
        event("saved_edits_error", {{"error", savedError}});
    }
}
void Editor::trackEdits(const std::vector<EditPose> &poses) {
    for (const EditPose &pose : poses) {
        Json record = savedRecord(pose.target);
        if (record.is_null()) {
            if (pose.changed) unsavableChanges.insert(pose.id); else unsavableChanges.erase(pose.id);
            continue;
        }
        std::string key = record.at("target").dump();
        Json after = pose.changed ? record : Json();
        Json stored = savedRecords.contains(key) ? savedRecords.at(key) : Json();
        if (same(after, stored)) pendingRecords.erase(key);
        else pendingRecords[key] = std::move(after);
    }
}
void Editor::saveChanges() {
    requirePaused();
    if (!savedError.empty()) throw std::runtime_error("Saved edits could not be read; clear that save before replacing it");
    if (pendingRecords.empty() && !unsavableChanges.empty())
        throw std::runtime_error("These items have no stable source and can only be edited for this run");
    Json next = savedRecords;
    for (auto it = pendingRecords.begin(); it != pendingRecords.end(); ++it)
        if (it.value().is_null()) next.erase(it.key()); else next[it.key()] = it.value();
    if (next.size() > recordLimit) throw std::runtime_error("Save supports up to 8192 edited objects");
    saveLocalJson(state.files + "/level-edits.json", fileData(next));
    savedRecords = std::move(next); pendingRecords.clear(); ++saveCount;
    state.message = "Saved " + std::to_string(savedRecords.size()) + " object edits for future runs";
    if (!unsavableChanges.empty()) state.message += " · " + std::to_string(unsavableChanges.size()) + " temporary items were not saved";
    if (!play.savedEdits) state.message += " · enable Use saved edits for the next run";
    event("level_edits_saved", {{"count", savedRecords.size()}, {"temporary_items", unsavableChanges.size()}});
}
void Editor::forgetSaved() {
    requirePaused();
    saveLocalJson(state.files + "/level-edits.json", fileData(Json::object()));
    savedRecords.clear(); pendingRecords.clear(); unsavableChanges.clear(); savedError.clear();
    state.message = "Saved edits cleared · restart the level to see its original geometry";
    event("saved_edits_forgotten");
}
Json Editor::savedInfo() {
    return {{"format", 1}, {"saved", savedRecords.size()}, {"unsaved", pendingRecords.size()},
        {"temporary", unsavableChanges.size()}, {"applied", savedApplied}, {"skipped", savedSkipped},
        {"saves", saveCount}, {"enabled", play.savedEdits}, {"error", savedError},
        {"file", "level-edits.json"}};
}
void Editor::applySavedBatch(Segment &s) {
    if (!play.savedEdits || !s.mapped || s.originalVertices.empty()) return;
    bool changed = false;
    for (auto &b : s.boxes) {
        if (!b.editable) continue;
        Selection target{Selection::Box, s.batch, b.ordinal};
        Json current = savedRecord(target);
        std::string key = current.at("target").dump();
        if (!savedRecords.contains(key)) continue;
        try {
            const auto &record = savedRecords.at(key);
            if (!same(record.at("baseline"), current.at("baseline"))) throw std::runtime_error("Source geometry differs from saved box");
            Vec3 p = savedVector(record.at("position")); p.z += s.offset;
            applyBox(s, b, p, rotation(record.at("rotation")), savedVector(record.at("scale")), false);
            ++savedApplied; changed = true;
        } catch (const std::exception &error) {
            ++savedSkipped; event("saved_edit_skipped", {{"target", current.at("target")}, {"reason", error.what()}});
        }
    }
    if (changed) {
        engine.bodyMass(ptr(s.room, off::roomBody)); upload(s);
        event("saved_segment_edits_applied", {{"id", s.id}, {"source", s.source}, {"occurrence", s.occurrence}});
    }
}
void Editor::obstacleCreated(void *room, void *obstacle, const Transform *definitionTransform) {
    auto sources = definitionSources.find(room);
    if (!obstacle || sources == definitionSources.end()) return;
    int index = -1;
    void *definitions = ptr(room, off::roomDefs + 8);
    for (int i = 0, n = count(room, off::roomDefs); i < n && i < 20000; ++i)
        if (at(definitions, i * off::obstacleDefStride + off::defTransform) == definitionTransform) { index = i; break; }
    auto source = sources->second.find(index);
    if (source == sources->second.end()) return;
    auto entities = array(obstacle, off::obstacleEntities);
    Transform roomPose = read<Transform>(ptr(room, off::roomBody), off::entityTransform);
    for (size_t i = 0; i < entities.size(); ++i) {
        void *body = entities[i];
        if (count(body, off::entityType) != 0 || read<uint8_t>(body, 0x56) || count(body, off::bodyShapes) <= 0) continue;
        chooseBody(body);
        BodyEdit &b = bodies.at(body);
        b.sourceTarget = source->second.target;
        b.sourceTarget["kind"] = "body"; b.sourceTarget["entity"] = i;
        b.sourceRoom = room; b.sourceOffset = source->second.offset;
        b.sourceOriginal = {roomPose.rotation.inverse().rotate(b.original.position - roomPose.position),
                            roomPose.rotation.inverse() * b.original.rotation};
        b.sourceOriginal.position.z -= b.sourceOffset;
        applySavedBody(b);
    }
}
void Editor::applySavedBody(BodyEdit &b) {
    if (!play.savedEdits) return;
    std::string key = b.sourceTarget.dump();
    if (!savedRecords.contains(key)) return;
    try {
        const auto &record = savedRecords.at(key);
        if (!same(record.at("baseline"), geometrySignature(b))) throw std::runtime_error("Authored item geometry differs from the saved item");
        Transform room = read<Transform>(ptr(b.sourceRoom, off::roomBody), off::entityTransform);
        Vec3 p = savedVector(record.at("position")); p.z += b.sourceOffset;
        applyBody(b, {room.position + room.rotation.rotate(p), room.rotation * rotation(record.at("rotation"))},
                  savedVector(record.at("scale")));
        b.changed = true; ++savedApplied;
        event("saved_body_edit_applied", {{"id", b.id}, {"target", b.sourceTarget}});
    } catch (const std::exception &error) {
        ++savedSkipped; event("saved_edit_skipped", {{"target", b.sourceTarget}, {"reason", error.what()}});
    }
}
}
