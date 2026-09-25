#include "editor.hpp"
#include <set>
#include <stdexcept>

namespace shdev {
Editor editor;
namespace {
std::vector<Vec3> polyVertices(void *shape) {
    void *poly = at(shape, off::shapePoly);
    int n = count(poly, 0);
    void *p = ptr(poly, 8);
    if (n < 0 || n > 65536 || (!p && n))
        throw std::runtime_error("Invalid native polyhedron");
    std::vector<Vec3> out;
    out.reserve(n);
    for (int i = 0; i < n; i++)
        out.push_back(read<Vec3>(p, i * 24));
    return out;
}
void setPoly(void *shape, const std::vector<Vec3> &vertices) {
    void *poly = at(shape, off::shapePoly);
    if (count(poly, 0) != static_cast<int>(vertices.size()))
        throw std::runtime_error("Shape topology changed; select again");
    void *p = ptr(poly, 8);
    for (size_t i = 0; i < vertices.size(); i++)
        write(p, i * 24, vertices[i]);
    engine.polyNormals(poly, true);
}
Transform bodyTransform(void *body) {
    return read<Transform>(body, off::entityTransform);
}
Vec3 point(Transform t, Vec3 p) {
    return t.position + t.rotation.rotate(p);
}
Vec3 inversePoint(Transform t, Vec3 p) {
    return t.rotation.inverse().rotate(p - t.position);
}
Bounds bodyGeometryBounds(void *body) {
    Bounds b;
    Transform tr = bodyTransform(body);
    for (void *shape : array(body, off::bodyShapes))
        for (Vec3 p : polyVertices(shape))
            b.add(point(tr, p));
    return b;
}
std::string obstacleName(void *body) {
    void *obstacle = ptr(body, off::entityObstacle);
    if (!obstacle)
        return "unowned";
    void *room = ptr(obstacle);
    if (!room)
        return "unknown";
    if (ptr(room, off::roomRootObstacle) == obstacle)
        return "room script: " + qiString(at(room, off::roomName));
    int n = count(room, off::roomDefs);
    void *p = ptr(room, off::roomDefs + 8);
    for (int i = 0; i < n && i < 20000; i++) {
        void *d = at(p, i * off::obstacleDefStride);
        if (ptr(d, off::defInstance) == obstacle)
            return qiString(d);
    }
    return "script obstacle";
}
void validateScale(Vec3 s) {
    if (s.x < .01f || s.y < .01f || s.z < .01f || s.x > 100 || s.y > 100 || s.z > 100)
        throw std::runtime_error("Scale factors must be between 0.01 and 100");
}
Json boundsJson(Bounds b) {
    return b.valid() ? Json{{"min", jvec(state.world(b.min))}, {"max", jvec(state.world(b.max))}}
                     : Json();
}
std::string checksum(const std::vector<Vec3> &vertices) {
    uint64_t hash = 1469598103934665603ull;
    for (auto &v : vertices) {
        const auto *data = reinterpret_cast<const uint8_t *>(&v);
        for (size_t i = 0; i < sizeof(v); i++) {
            hash ^= data[i];
            hash *= 1099511628211ull;
        }
    }
    char value[32];
    snprintf(value, sizeof(value), "%016llx", static_cast<unsigned long long>(hash));
    return value;
}
} // namespace

void Editor::segmentCreated(void *room, const std::string &source, float offset,
                            const std::vector<void *> &beforeShapes,
                            const std::vector<void *> &beforeBatches, int beforeDefinitions) {
    auto batches = array(room, off::roomBatches);
    auto shapes = array(ptr(room, off::roomBody), off::bodyShapes);
    for (void *batch : batches)
        if (std::find(beforeBatches.begin(), beforeBatches.end(), batch) == beforeBatches.end()) {
            Segment s;
            s.room = room;
            s.batch = batch;
            s.id = state.id(batch);
            s.offset = offset;
            s.source = qiString(at(batch, off::batchName));
            std::string path = s.source;
            if (path.rfind("segments/", 0) == 0)
                path = path.substr(9);
            if (path.size() > 5 && path.substr(path.size() - 5) == ".mesh")
                path.resize(path.size() - 5);
            try {
                auto data = readAsset("shdev/geometry/" + path + ".json");
                if (data.empty())
                    throw std::runtime_error("No source mapping");
                auto map = Json::parse(data);
                s.source = map.at("source").get<std::string>();
                s.expectedVertices = map.at("vertex_count");
                s.owners = map.at("owners").get<std::vector<int>>();
                std::vector<void *> created;
                for (void *shape : shapes)
                    if (std::find(beforeShapes.begin(), beforeShapes.end(), shape) ==
                        beforeShapes.end())
                        created.push_back(shape);
                bool valid = created.size() == map.at("boxes").size();
                for (auto &b : map.at("boxes")) {
                    BoxEdit box;
                    box.ordinal = b.at("ordinal");
                    box.sourceIndex = b.at("source_index");
                    box.center = vec(b.at("position"));
                    box.center.z += offset;
                    box.position = box.center;
                    box.half = vec(b.at("half_extents"));
                    box.attributes = b.at("attributes");
                    box.editable = valid && b.at("editable").get<bool>();
                    box.shape = valid ? created.at(box.ordinal) : nullptr;
                    for (int quad : b.at("quads"))
                        for (int j = 0; j < 4; j++)
                            box.vertices.push_back(quad * 4 + j);
                    if (box.shape)
                        box.originalPoly = polyVertices(box.shape);
                    s.boxes.push_back(std::move(box));
                }
                s.mapped = valid;
                if (!valid)
                    s.reason = "Native collider count differs from source box count; per-box edits "
                               "disabled";
            } catch (const std::exception &e) {
                s.reason = e.what();
            }
            event("segment_created", {{"id", s.id},
                                      {"room", state.id(room)},
                                      {"source", s.source},
                                      {"offset", offset},
                                      {"mapped", s.mapped},
                                      {"boxes", s.boxes.size()},
                                      {"reason", s.reason}});
            for (const auto &[p, previous] : segments)
                if (previous.room == room && previous.source == s.source) ++s.occurrence;
            // Room::createSegment appends the actual authored obstacle defs.
            // Associate those entries with their source piece while that
            // construction boundary is observable, before pointers can move.
            int afterDefinitions = count(room, off::roomDefs);
            if (afterDefinitions >= beforeDefinitions && afterDefinitions <= 20000) {
                void *defs = ptr(room, off::roomDefs + 8);
                for (int i = beforeDefinitions; i < afterDefinitions; ++i) {
                    Json target = segmentTarget(s);
                    target["obstacle"] = i - beforeDefinitions;
                    target["obstacle_name"] = qiString(at(defs, i * off::obstacleDefStride));
                    definitionSources[room][i] = {target, offset};
                }
            }
            segments[batch] = std::move(s);
        }
}
void Editor::batchLoaded(void *batch) {
    auto it = segments.find(batch);
    if (it == segments.end())
        return;
    auto &s = it->second;
    invalidateHistory(batch);
    if (std::any_of(selected.begin(), selected.end(), [batch](Selection s) { return s.target == batch; }))
        ++selectionRevision;
    void *vb = at(batch, off::batchVbo);
    int n = count(vb, off::vboCount), stride = count(vb, off::vboStride);
    void *p = ptr(vb, off::vboData);
    if (n < 0 || n > 1000000 || stride < 12 || stride > 256 || (!p && n)) {
        s.mapped = false;
        s.reason = "Unexpected vertex buffer layout";
        return;
    }
    s.originalVertices.clear();
    s.originalVertices.reserve(n);
    for (int i = 0; i < n; i++)
        s.originalVertices.push_back(read<Vec3>(p, i * stride));
    if (n != s.expectedVertices) {
        s.mapped = false;
        s.reason = "Native vertex count differs from mapped mesh";
        for (auto &b : s.boxes)
            b.editable = false;
    }
    applySavedBatch(s);
}
void Editor::roomDestroyed(void *room) {
    definitionSources.erase(room);
    for (auto it = segments.begin(); it != segments.end();) {
        if (it->second.room == room) {
            discardTarget(it->first);
            state.ids.erase(it->first);
            it = segments.erase(it);
        } else
            ++it;
    }
}
void Editor::entityDestroyed(void *entity) {
    discardTarget(entity);
    bodies.erase(entity);
}
void Editor::clear() {
    pointerDrag = {};
    lastRayHit = nullptr;
    clearSelection();
    undoStack.clear();
    redoStack.clear();
    segments.clear();
    bodies.clear();
    definitionSources.clear();
}

void Editor::chooseBody(void *body) {
    if (!bodies.count(body)) {
        BodyEdit b;
        b.body = body;
        b.id = state.id(body);
        b.original = bodyTransform(body);
        b.originalWorld = state.world(b.original.position);
        for (void *s : array(body, off::bodyShapes))
            b.originalPoly[s] = polyVertices(s);
        bodies[body] = std::move(b);
    }
}
bool Editor::selectId(uint64_t id, int box, bool additive) {
    for (auto &[p, s] : segments)
        if (s.id == id) {
            if (box >= 0 && box < static_cast<int>(s.boxes.size()))
                setSelection({Selection::Box, p, box}, additive);
            else
                setSelection({Selection::SegmentMesh, p, -1}, additive);
            return true;
        }
    for (void *body : array(engine.level(), off::levelBodies))
        if (state.id(body) == id) {
            bool roomBody = false;
            for (auto &[p, s] : segments)
                if (ptr(s.room, off::roomBody) == body)
                    roomBody = true;
            if (roomBody)
                return false;
            chooseBody(body);
            setSelection({Selection::Body, body, -1}, additive);
            return true;
        }
    return false;
}
Vec3 Editor::pick(float x, float y, float aspect, bool additive, bool preserveGroup) {
    void *display = ptr(engine.game(), off::gameDisplay);
    Vec3 origin = state.freeCamera ? state.camera : read<Vec3>(display, off::displayPosition);
    Quat rotation = state.freeCamera ? state.rotation() : read<Quat>(display, off::displayRotation);
    float fov = state.freeCamera ? state.fov : read<float>(at(display, off::viewport), 0x20);
    float t = std::tan(fov * PI / 360.f);
    Vec3 direction =
        rotation.rotate(Vec3{(2 * x - 1) * t, (1 - 2 * y) * t / aspect, -1}.normalized());
    float best = INFINITY;
    Selection hit;
    for (auto &[batch, s] : segments) {
        if (!read<uint8_t>(batch, off::batchLoaded))
            continue;
        void *vb = at(batch, off::batchVbo);
        void *ib = at(batch, off::batchIbo);
        int n = count(vb, off::vboCount), stride = count(vb, off::vboStride),
            ni = count(ib, off::iboCount);
        void *vertices = ptr(vb, off::vboData);
        void *indices = ptr(ib, off::iboData);
        if (n <= 0 || n > 1000000 || ni < 0 || ni > 6000000 || !vertices || !indices)
            continue;
        Transform tr = bodyTransform(ptr(s.room, off::roomBody));
        Vec3 o = inversePoint(tr, origin), d = tr.rotation.inverse().rotate(direction);
        if (!state.freeCamera) {
            float cz = inversePoint(tr, read<Vec3>(engine.level(), off::levelPosition)).z;
            if (!(read<float>(batch) < cz && cz < read<float>(batch, 4) + 25))
                continue;
        }
        for (int i = 0; i + 2 < ni; i += 3) {
            uint16_t a = read<uint16_t>(indices, 2 * i), b = read<uint16_t>(indices, 2 * (i + 1)),
                     c = read<uint16_t>(indices, 2 * (i + 2));
            if (a >= n || b >= n || c >= n)
                continue;
            float distance =
                rayTriangle(o, d, read<Vec3>(vertices, a * stride),
                            read<Vec3>(vertices, b * stride), read<Vec3>(vertices, c * stride));
            if (distance < best) {
                best = distance;
                int owner = s.mapped && a / 4 < s.owners.size() ? s.owners[a / 4] : -1;
                hit = {owner >= 0 ? Selection::Box : Selection::SegmentMesh, batch, owner};
            }
        }
    }
    std::set<void *> roomBodies;
    for (auto &[p, s] : segments)
        roomBodies.insert(ptr(s.room, off::roomBody));
    for (void *body : array(engine.level(), off::levelBodies)) {
        if (roomBodies.count(body) || !read<uint8_t>(body, 0x15c))
            continue;
        // Native Body::computeBounds in this build does not union every shape's
        // maximum. Use the actual transformed polyhedra for editor selection.
        Bounds bound = bodyGeometryBounds(body);
        if (!bound.valid() || !rayBounds(origin, direction, bound, best))
            continue;
        Transform tr = bodyTransform(body);
        Vec3 o = inversePoint(tr, origin), d = tr.rotation.inverse().rotate(direction);
        for (void *shape : array(body, off::bodyShapes)) {
            // Shape +0x60 selects a collision tree; static shapes can be visible.
            // These are the material/alpha tests in RenderLevel::fillBuffers.
            if (read<float>(shape, 0x15c) == 0 || count(shape, 0x14c) == 4)
                continue;
            void *poly = at(shape, off::shapePoly);
            void *vertices = ptr(poly, 8), *edges = ptr(poly, off::polyEdges + 8),
                 *faces = ptr(poly, off::polyFaces + 8);
            int nv = count(poly, 0), ne = count(poly, off::polyEdges),
                nf = count(poly, off::polyFaces);
            if (nv < 3 || nv > 65536 || ne < 3 || ne > 65536 || nf < 1 || nf > 65536)
                continue;
            for (int f = 0; f < nf; f++) {
                int start = read<int16_t>(faces, f * 20), e = start;
                std::vector<int> v;
                do {
                    if (e < 0 || e >= ne || v.size() > static_cast<size_t>(ne)) {
                        v.clear();
                        break;
                    }
                    int index = read<int16_t>(edges, e * 8);
                    if (index < 0 || index >= nv) {
                        v.clear();
                        break;
                    }
                    v.push_back(index);
                    e = read<int16_t>(edges, e * 8 + 2);
                } while (e != start);
                for (size_t i = 1; i + 1 < v.size(); i++) {
                    float distance = rayTriangle(o, d, read<Vec3>(vertices, v[0] * 24),
                                                 read<Vec3>(vertices, v[i] * 24),
                                                 read<Vec3>(vertices, v[i + 1] * 24));
                    if (distance < best) {
                        best = distance;
                        hit = {Selection::Body, body, -1};
                    }
                }
            }
        }
    }
    if (hit.kind == Selection::Body)
        chooseBody(hit.target);
    if (preserveGroup && hit.kind != Selection::None &&
        std::find(selected.begin(), selected.end(), hit) != selected.end()) {
        if (!(selection == hit)) ++selectionRevision;
        selection = hit;
    } else setSelection(hit, additive);
    state.message =
        hit.kind == Selection::None ? "No visible object at this point" : "Selected real geometry";
    Vec3 point = hit.kind == Selection::None ? Vec3{} : state.world(origin + direction * best);
    lastRayHit = hit.kind == Selection::None ? Json() : jvec(point);
    event("selection", {{"x", x}, {"y", y}, {"hit", info()}, {"hit_world", lastRayHit}});
    return point;
}

Bounds Editor::selectedBounds() {
    return boundsFor(selection);
}
Bounds Editor::boundsFor(Selection target) {
    Bounds b;
    if (!live(target))
        return b;
    if (target.kind == Selection::Body)
        return bodyGeometryBounds(target.target);
    auto it = segments.find(target.target);
    if (it == segments.end())
        return b;
    auto &s = it->second;
    Transform tr = bodyTransform(ptr(s.room, off::roomBody));
    if (target.kind == Selection::Box) {
        auto &box = s.boxes.at(target.box);
        if (box.shape) {
            for (Vec3 p : polyVertices(box.shape))
                b.add(point(tr, p));
        } else {
            for (int i = 0; i < 8; i++)
                b.add(point(tr, box.position +
                                    box.rotation.rotate(Vec3{i & 1 ? box.half.x : -box.half.x,
                                                             i & 2 ? box.half.y : -box.half.y,
                                                             i & 4 ? box.half.z : -box.half.z}
                                                            .mul(box.scale))));
        }
    } else if (read<uint8_t>(s.batch, off::batchLoaded)) {
        void *vb = at(s.batch, off::batchVbo);
        int n = count(vb, off::vboCount), stride = count(vb, off::vboStride);
        for (int i = 0; i < n; i++)
            b.add(point(tr, read<Vec3>(ptr(vb, off::vboData), i * stride)));
    }
    return b;
}
Json Editor::info() {
    if (selection.kind == Selection::None)
        return nullptr;
    Json out;
    out["bounds"] = boundsJson(selectedBounds());
    if (selection.kind == Selection::Body) {
        auto it = bodies.find(selection.target);
        if (it == bodies.end()) {
            selection = {};
            return nullptr;
        }
        auto &b = it->second;
        void *body = b.body;
        Transform t = bodyTransform(body);
        void *obs = ptr(body, off::entityObstacle);
        void *room = obs ? ptr(obs) : nullptr;
        auto shapes = array(body, off::bodyShapes);
        int vertices = 0, faces = 0;
        Json materials = Json::array();
        for (void *s : shapes) {
            vertices += count(s, off::shapePoly);
            faces += count(s, off::shapePoly + off::polyFaces);
            materials.push_back(
                {{"type", count(s, 0x14c)},
                 {"density", read<float>(s, 0x138)},
                 {"color", Json::array({read<float>(s, 0x150), read<float>(s, 0x154),
                                        read<float>(s, 0x158), read<float>(s, 0x15c)})}});
        }
        out.update({{"kind", "body"},
                    {"id", b.id},
                    {"native_address", pointer(body)},
                    {"entity_type", count(body, off::entityType)},
                    {"name", obstacleName(body)},
                    {"parent_obstacle", pointer(obs)},
                    {"room", state.id(room)},
                    {"position", jvec(state.world(t.position))},
                    {"rotation_degrees", jvec(t.rotation.euler() * (180 / PI))},
                    {"scale_factor", jvec(b.scale)},
                    {"editable", editable(selection)},
                    {"collider_count", shapes.size()},
                    {"vertices", vertices},
                    {"faces", faces},
                    {"materials", materials},
                    {"dynamic", bool(read<uint8_t>(body, 0x55))},
                    {"joints", count(body, off::bodyJoints)},
                    {"can_save", !b.sourceTarget.is_null()},
                    {"persistence", b.sourceTarget.is_null() ? "This item has no stable authored source; current run only"
                                                            : "Save edits to restore this authored item on future runs; scripts still control its motion"}});
        std::vector<Vec3> geometry;
        for (void *shape : shapes) {
            auto v = polyVertices(shape);
            geometry.insert(geometry.end(), v.begin(), v.end());
        }
        out["geometry_checksum"] = checksum(geometry);
        out["bounds_source"] = "Transformed native polyhedron vertices";
        out["native_entity_bounds"] = boundsJson(
            {read<Vec3>(body, off::entityBounds), read<Vec3>(body, off::entityBounds + 12)});
        if (read<uint8_t>(body, 0x56)) {
            out["editable"] = false;
            out["reason"] =
                "Ball/model rendering is separate from its collision polyhedron; inspect only";
        }
        return out;
    }
    auto it = segments.find(selection.target);
    if (it == segments.end()) {
        selection = {};
        return nullptr;
    }
    auto &s = it->second;
    Transform tr = bodyTransform(ptr(s.room, off::roomBody));
    out["box_choices"] = Json::array();
    for (const auto &box : s.boxes)
        out["box_choices"].push_back({{"box", box.ordinal}, {"source_index", box.sourceIndex},
                                      {"editable", editable({Selection::Box, s.batch, box.ordinal})}});
    out.update({{"id", s.id},
                {"room", state.id(s.room)},
                {"source", s.source},
                {"mesh", qiString(at(s.batch, off::batchName))},
                {"native_address", pointer(s.batch)},
                {"parent", "Room static body"}, {"source_occurrence", s.occurrence}});
    if (selection.kind == Selection::Box) {
        auto &b = s.boxes.at(selection.box);
        out.update(
            {{"kind", "box"},
             {"name", "XML box #" + std::to_string(b.sourceIndex)},
             {"box", b.ordinal},
             {"source_index", b.sourceIndex},
             {"position", jvec(state.world(point(tr, b.position)))},
             {"rotation_degrees", jvec((tr.rotation * b.rotation).euler() * (180 / PI))},
             {"scale_factor", jvec(b.scale)},
             {"half_extents", jvec(b.half)},
             {"editable", editable(selection)},
             {"can_save", editable(selection)},
             {"persistence", "Save edits to restore this source box on future runs"},
             {"collider", pointer(b.shape)},
             {"mesh_vertices", b.vertices.size()},
             {"attributes", b.attributes},
             {"changed", b.changed},
             {"limitation",
              "Only originally baked faces exist; moving can expose missing interior faces"}});
        std::vector<Vec3> actual;
        void *vb = at(s.batch, off::batchVbo);
        if (read<uint8_t>(s.batch, off::batchLoaded))
            for (int i : b.vertices)
                actual.push_back(read<Vec3>(ptr(vb, off::vboData), i * count(vb, off::vboStride)));
        out["mesh_position_checksum"] = checksum(actual);
        if (b.shape)
            out["collider_position_checksum"] = checksum(polyVertices(b.shape));
        if (!actual.empty())
            out["mesh_first_vertex"] = jvec(actual.front());
    } else
        out.update({{"kind", "segment_mesh"},
                    {"name", s.source},
                    {"editable", false},
                    {"position", jvec(state.world(selectedBounds().center()))},
                    {"reason", s.reason.empty()
                                   ? "Unmapped or ambiguous face: inspect only; select a mapped box"
                                   : s.reason}});
    return out;
}
Json Editor::objects() {
    Json result = Json::array();
    for (auto &[p, s] : segments) {
        int editable = 0;
        for (auto &b : s.boxes)
            if (b.editable)
                editable++;
        result.push_back({{"id", s.id},
                          {"kind", "segment_mesh"},
                          {"name", s.source},
                          {"room", state.id(s.room)},
                          {"boxes", s.boxes.size()},
                          {"editable_boxes", editable},
                          {"loaded", bool(read<uint8_t>(p, off::batchLoaded))}});
    }
    std::set<void *> roomBodies;
    for (auto &[p, s] : segments)
        roomBodies.insert(ptr(s.room, off::roomBody));
    for (void *b : array(engine.level(), off::levelBodies))
        if (!roomBodies.count(b))
            result.push_back({{"id", state.id(b)},
                              {"kind", "body"},
                              {"name", obstacleName(b)},
                              {"position", jvec(state.world(bodyTransform(b).position))},
                              {"bounds", boundsJson(bodyGeometryBounds(b))},
                              {"editable", !read<uint8_t>(b, 0x56) && count(b, off::bodyShapes) > 0},
                              {"shapes", count(b, off::bodyShapes)}});
    return result;
}
void Editor::upload(Segment &s) {
    void *vb = at(s.batch, off::batchVbo);
    Bounds b;
    int n = count(vb, off::vboCount), stride = count(vb, off::vboStride);
    for (int i = 0; i < n; i++)
        b.add(read<Vec3>(ptr(vb, off::vboData), i * stride));
    if (b.valid()) {
        write(s.batch, 0, b.min.z);
        write(s.batch, 4, b.max.z);
    }
    engine.vboUpload(vb);
}
void Editor::applyBox(Segment &s, BoxEdit &b, Vec3 position, Quat rotation, Vec3 scale, bool flush) {
    if (!s.mapped || !b.editable || s.originalVertices.empty())
        throw std::runtime_error("This box has no unambiguous mesh/collider mapping");
    validateScale(scale);
    void *vb = at(s.batch, off::batchVbo);
    int n = count(vb, off::vboCount), stride = count(vb, off::vboStride);
    if (n != static_cast<int>(s.originalVertices.size()))
        throw std::runtime_error("Vertex buffer changed");
    std::vector<Vec3> poly;
    for (Vec3 p : b.originalPoly)
        poly.push_back(position + rotation.rotate((p - b.center).mul(scale)));
    // Validate before touching either representation.
    if (count(b.shape, off::shapePoly) != static_cast<int>(poly.size()))
        throw std::runtime_error("Collider topology changed");
    for (int index : b.vertices)
        if (index < 0 || index >= n)
            throw std::runtime_error("Mapping index out of bounds");
    for (int index : b.vertices)
        write(ptr(vb, off::vboData), index * stride,
              position + rotation.rotate((s.originalVertices[index] - b.center).mul(scale)));
    setPoly(b.shape, poly);
    if (flush) {
        engine.bodyMass(ptr(s.room, off::roomBody));
        upload(s);
    }
    b.position = position;
    b.rotation = rotation;
    b.scale = scale;
    b.changed = true;
}
void Editor::applyBody(BodyEdit &b, Transform transform, Vec3 scale) {
    validateScale(scale);
    auto shapes = array(b.body, off::bodyShapes);
    if (shapes.size() != b.originalPoly.size())
        throw std::runtime_error("Body topology changed; select again");
    for (void *s : shapes) {
        if (!b.originalPoly.count(s) ||
            b.originalPoly.at(s).size() != static_cast<size_t>(count(s, off::shapePoly)))
            throw std::runtime_error("Body topology changed");
    }
    for (void *s : shapes) {
        std::vector<Vec3> v;
        for (Vec3 p : b.originalPoly.at(s))
            v.push_back(p.mul(scale));
        setPoly(s, v);
    }
    engine.bodyMass(b.body);
    engine.bodyTransform(b.body, &transform);
    b.scale = scale;
}
void Editor::transform(const Json &command) {
    requirePaused();
    Json before = info();
    if (before.is_null() || !before.value("editable", false))
        throw std::runtime_error("Select an editable box or body");
    EditAction action;
    action.before = {capture(selection)};
    EditPose after = action.before.front();
    after.position = vec(command.at("position"));
    after.rotation = Quat::euler(vec(command.at("rotation_degrees")) * (PI / 180));
    after.scale = vec(command.at("scale"), {1, 1, 1});
    after.changed = true;
    action.after = {after};
    applyPoses(action.after);
    remember(std::move(action));
    event("transform", {{"before", before}, {"after", info()}});
    state.message = "Updated native geometry and collision bounds";
}
void Editor::resetSelected() {
    requirePaused();
    if (!editable(selection))
        throw std::runtime_error("Select an editable object first");
    EditAction action;
    action.before = {capture(selection)};
    EditPose after = action.before.front();
    if (selection.kind == Selection::Box) {
        auto &s = segments.at(selection.target);
        auto &b = s.boxes.at(selection.box);
        Transform tr = bodyTransform(ptr(s.room, off::roomBody));
        after.position = state.world(point(tr, b.center));
        after.rotation = tr.rotation;
    } else if (selection.kind == Selection::Body) {
        auto &b = bodies.at(selection.target);
        Transform baseline = originalBodyPose(b);
        after.position = state.world(baseline.position);
        after.rotation = baseline.rotation;
    }
    after.scale = {1, 1, 1};
    after.changed = false;
    action.after = {after};
    applyPoses(action.after);
    remember(std::move(action));
    state.message = "Restored captured original geometry";
    event("object_reset", {{"object", info()}});
}
void Editor::reloadSection() {
    requirePaused();
    void *batch = (selection.kind == Selection::Box || selection.kind == Selection::SegmentMesh)
                      ? selection.target
                      : nullptr;
    if (!batch) {
        void *room = ptr(engine.level(), off::levelCurrent);
        float best = INFINITY;
        for (auto &[p, s] : segments)
            if (s.room == room) {
                float z = bodyTransform(ptr(room, off::roomBody)).position.z +
                          (read<float>(p) + read<float>(p, 4)) * .5f;
                float d = std::abs(z - read<Vec3>(engine.level(), off::levelPosition).z);
                if (d < best) {
                    best = d;
                    batch = p;
                }
            }
    }
    if (!batch)
        throw std::runtime_error("No current segment is retained");
    auto &s = segments.at(batch);
    // Native load rereads and decompresses the packaged mesh, reinitializing its
    // existing buffers. Its matching colliders are restored from captured XML
    // construction geometry. This does not respawn already expired Lua objects.
    for (auto &b : s.boxes)
        if (b.changed && b.shape) {
            setPoly(b.shape, b.originalPoly);
            b.position = b.center;
            b.rotation = {};
            b.scale = {1, 1, 1};
            b.changed = false;
        }
    engine.bodyMass(ptr(s.room, off::roomBody));
    engine.batchLoad(batch);
    batchLoaded(batch);
    event("segment_reloaded", {{"id", s.id}, {"source", s.source}});
    state.message = "Segment mesh reloaded; collider edits reset. Lua objects unchanged.";
}
void Editor::exportEdits() {
    Json patches = Json::array();
    for (auto &[p, s] : segments)
        for (auto &b : s.boxes)
            if (b.changed) {
                Vec3 local = b.position;
                local.z -= s.offset;
                patches.push_back({{"source", s.source},
                                   {"source_index", b.sourceIndex},
                                   {"room_instance", state.id(s.room)},
                                   {"segment_instance", s.id},
                                   {"position_in_segment", jvec(local)},
                                   {"rotation_degrees", jvec(b.rotation.euler() * (180 / PI))},
                                   {"scale_factor", jvec(b.scale)}});
            }
    writeFile(state.files + "/edits.json",
              Json{{"version", 1},
                   {"build_id", engine.buildId},
                   {"note", "Runtime patch record, not a rebuilt .mesh; apply/export tooling can "
                            "consume source indices"},
                   {"patches", patches}}
                  .dump(2));
    state.message = "Exported edits.json to app files/shdev";
    event("edits_exported", {{"count", patches.size()}});
}
Json Editor::lines(float aspect) {
    Json lines = Json::array();
    if (!state.enabled)
        return lines;
    void *display = ptr(engine.game(), off::gameDisplay);
    Vec3 camera = state.freeCamera ? state.camera : read<Vec3>(display, off::displayPosition);
    Quat inverse =
        (state.freeCamera ? state.rotation() : read<Quat>(display, off::displayRotation)).inverse();
    float fov = state.freeCamera ? state.fov : read<float>(at(display, off::viewport), 0x20);
    float tan = std::tan(fov * PI / 360);
    auto line = [&](Vec3 a, Vec3 b, const std::string &color) {
        a = inverse.rotate(a - camera);
        b = inverse.rotate(b - camera);
        if (a.z >= -.02f && b.z >= -.02f)
            return;
        if (a.z >= -.02f)
            a = a + (b - a) * ((-.02f - a.z) / (b.z - a.z));
        if (b.z >= -.02f)
            b = b + (a - b) * ((-.02f - b.z) / (a.z - b.z));
        float x1 = .5f + .5f * a.x / (-a.z * tan), y1 = .5f - .5f * a.y * aspect / (-a.z * tan),
              x2 = .5f + .5f * b.x / (-b.z * tan), y2 = .5f - .5f * b.y * aspect / (-b.z * tan);
        if (std::isfinite(x1) && std::isfinite(y1) && std::isfinite(x2) && std::isfinite(y2))
            lines.push_back(Json::array({x1, y1, x2, y2, color}));
    };
    auto box = [&](Bounds b, const std::string &color) {
        if (!b.valid())
            return;
        Vec3 p[8];
        for (int i = 0; i < 8; i++)
            p[i] = {i & 1 ? b.max.x : b.min.x, i & 2 ? b.max.y : b.min.y,
                    i & 4 ? b.max.z : b.min.z};
        for (int i = 0; i < 8; i++)
            for (int bit = 1; bit <= 4; bit *= 2)
                if (!(i & bit))
                    line(p[i], p[i | bit], color);
    };
    if (state.bounds)
        for (auto &[p, s] : segments)
            if (read<uint8_t>(p, off::batchLoaded)) {
                Bounds b;
                Transform tr = bodyTransform(ptr(s.room, off::roomBody));
                void *vb = at(p, off::batchVbo);
                void *data = ptr(vb, off::vboData);
                int n = count(vb, off::vboCount), stride = count(vb, off::vboStride);
                for (int i = 0; i < n; i++)
                    b.add(point(tr, read<Vec3>(data, i * stride)));
                box(b, ptr(engine.level(), off::levelCurrent) == s.room ? "#4bd6b5" : "#60a5fa");
            }
    for (size_t i = 0; i < std::min<size_t>(selected.size(), 64); ++i)
        box(boundsFor(selected[i]), "#ffd166");
    if (selected.size() > 1)
        box(groupBounds(), "#f8b84a");
    return lines;
}
} // namespace shdev
