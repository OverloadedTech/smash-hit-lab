#include "editor.hpp"
#include <set>
#include <stdexcept>

namespace shdev {
namespace {
constexpr size_t selectionLimit = 4096;
Vec3 axisVector(int axis) {
    if (axis == 0) return {1, 0, 0};
    if (axis == 1) return {0, 1, 0};
    if (axis == 2) return {0, 0, 1};
    throw std::runtime_error("Choose X, Y or Z");
}
void cameraPose(Vec3 &position, Quat &rotation, float &fov) {
    void *display = ptr(engine.game(), off::gameDisplay);
    position = state.world(state.freeCamera ? state.camera : read<Vec3>(display, off::displayPosition));
    rotation = state.freeCamera ? state.rotation() : read<Quat>(display, off::displayRotation);
    fov = state.freeCamera ? state.fov : read<float>(at(display, off::viewport), 0x20);
}
Vec3 screenRay(const Json &screen, const EditAction &action, float aspect) {
    if (!screen.is_array() || screen.size() != 2)
        throw std::runtime_error("Drag coordinates must contain X and Y");
    float x = screen[0], y = screen[1];
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(aspect) || aspect <= 0)
        throw std::runtime_error("Invalid screen coordinates");
    float t = std::tan(action.fov * PI / 360);
    return action.cameraRotation.rotate(Vec3{(2*x-1)*t, (1-2*y)*t/aspect, -1}.normalized());
}
Vec3 dragPoint(Vec3 direction, const EditAction &action, int axis) {
    if (axis == -1) {
        Vec3 normal = action.cameraRotation.rotate({0, 0, -1});
        float denominator = normal.dot(direction);
        if (std::abs(denominator) < .001f)
            throw std::runtime_error("Move pointer closer to the selected object");
        float distance = normal.dot(action.pivot - action.camera) / denominator;
        return action.camera + direction * distance;
    }
    Vec3 a = axisVector(axis), offset = action.camera - action.pivot;
    float b = direction.dot(a), denominator = 1-b*b;
    if (denominator < .002f)
        throw std::runtime_error("This axis points toward the camera; rotate the view first");
    float along = (a.dot(offset) - b * direction.dot(offset)) / denominator;
    return action.pivot + a * along;
}
}

void Editor::requirePaused() const {
    if (!state.frozen || state.stepRemaining > 0)
        throw std::runtime_error("Pause the world before editing");
}
bool Editor::live(Selection target) const {
    if (target.kind == Selection::Body)
        return bodies.count(target.target) != 0;
    if (target.kind != Selection::Box && target.kind != Selection::SegmentMesh)
        return false;
    auto it = segments.find(target.target);
    return it != segments.end() && (target.kind == Selection::SegmentMesh ||
        (target.box >= 0 && target.box < static_cast<int>(it->second.boxes.size())));
}
bool Editor::editable(Selection target) const {
    if (!live(target)) return false;
    if (target.kind == Selection::Body)
        return !read<uint8_t>(target.target, 0x56) && count(target.target, off::bodyShapes) > 0;
    if (target.kind != Selection::Box) return false;
    const auto &segment = segments.at(target.target);
    const auto &box = segment.boxes.at(target.box);
    return segment.mapped && box.editable && box.shape && !segment.originalVertices.empty() &&
           read<uint8_t>(segment.batch, off::batchLoaded);
}
void Editor::clearSelection() {
    selected.clear();
    selection = {};
    ++selectionRevision;
}
void Editor::setSelection(Selection target, bool additive) {
    if (!additive) selected.clear();
    if (target.kind != Selection::None) {
        auto found = std::find(selected.begin(), selected.end(), target);
        if (additive && found != selected.end()) selected.erase(found);
        else {
            // A whole-mesh inspection and one of its boxes are alternative
            // selection levels; never create overlapping parent/child edits.
            std::erase_if(selected, [&](Selection s) {
                return s.target == target.target &&
                    ((s.kind == Selection::SegmentMesh && target.kind == Selection::Box) ||
                     (s.kind == Selection::Box && target.kind == Selection::SegmentMesh));
            });
            if (selected.size() >= selectionLimit)
                throw std::runtime_error("Select at most 4096 objects at once");
            selected.push_back(target);
        }
    }
    selection = selected.empty() ? Selection{} : selected.back();
    ++selectionRevision;
}
void Editor::invalidateHistory(void *target) {
    auto references = [target](const EditAction &action) {
        return std::any_of(action.before.begin(), action.before.end(), [target](const EditPose &p) {
            return p.target.target == target;
        });
    };
    std::erase_if(undoStack, references);
    std::erase_if(redoStack, references);
}
void Editor::discardTarget(void *target) {
    invalidateHistory(target);
    size_t old = selected.size();
    std::erase_if(selected, [target](Selection s) { return s.target == target; });
    if (selected.size() != old) {
        selection = selected.empty() ? Selection{} : selected.back();
        ++selectionRevision;
    }
}
Bounds Editor::groupBounds() {
    Bounds result;
    for (Selection target : selected) {
        Bounds b = boundsFor(target);
        if (b.valid()) { result.add(b.min); result.add(b.max); }
    }
    return result;
}
EditPose Editor::capture(Selection target) {
    if (!editable(target)) throw std::runtime_error("The selection includes an inspect-only object");
    EditPose pose;
    pose.target = target;
    if (target.kind == Selection::Body) {
        const auto &body = bodies.at(target.target);
        Transform tr = read<Transform>(body.body, off::entityTransform);
        pose.id = body.id;
        pose.position = state.world(tr.position);
        pose.rotation = tr.rotation;
        pose.scale = body.scale;
        pose.changed = body.changed;
    } else {
        const auto &segment = segments.at(target.target);
        const auto &box = segment.boxes.at(target.box);
        Transform tr = read<Transform>(ptr(segment.room, off::roomBody), off::entityTransform);
        pose.id = segment.id;
        pose.position = state.world(tr.position + tr.rotation.rotate(box.position));
        pose.rotation = tr.rotation * box.rotation;
        pose.scale = box.scale;
        pose.changed = box.changed;
    }
    return pose;
}
void Editor::validate(const EditPose &pose) {
    if (!editable(pose.target)) throw std::runtime_error("An edited object is no longer available");
    if (!pose.position.finite() || !pose.scale.finite() || !std::isfinite(pose.rotation.x) ||
        !std::isfinite(pose.rotation.y) || !std::isfinite(pose.rotation.z) || !std::isfinite(pose.rotation.w))
        throw std::runtime_error("Transform values must be finite");
    if (std::max({std::abs(pose.position.x), std::abs(pose.position.y), std::abs(pose.position.z)}) > 1e7f)
        throw std::runtime_error("Position exceeds the supported coordinate range");
    Vec3 scale = pose.scale;
    if (scale.x < .01f || scale.y < .01f || scale.z < .01f || scale.x > 100 || scale.y > 100 || scale.z > 100)
        throw std::runtime_error("Scale factors must be between 0.01 and 100");
    if (pose.target.kind == Selection::Body) {
        const auto &body = bodies.at(pose.target.target);
        if (body.id != pose.id) throw std::runtime_error("The body instance changed");
        auto shapes = array(body.body, off::bodyShapes);
        if (shapes.size() != body.originalPoly.size()) throw std::runtime_error("Body topology changed");
        for (void *shape : shapes)
            if (!body.originalPoly.count(shape) ||
                count(shape, off::shapePoly) != static_cast<int>(body.originalPoly.at(shape).size()))
                throw std::runtime_error("Body topology changed");
    } else {
        const auto &segment = segments.at(pose.target.target);
        const auto &box = segment.boxes.at(pose.target.box);
        void *vb = at(segment.batch, off::batchVbo);
        int countNow = count(vb, off::vboCount);
        if (segment.id != pose.id || countNow != static_cast<int>(segment.originalVertices.size()) ||
            !ptr(vb, off::vboData) || count(vb, off::vboStride) < 12)
            throw std::runtime_error("The segment vertex buffer changed");
        if (count(box.shape, off::shapePoly) != static_cast<int>(box.originalPoly.size()))
            throw std::runtime_error("Collider topology changed");
        for (int i : box.vertices)
            if (i < 0 || i >= countNow) throw std::runtime_error("Mapping index out of bounds");
    }
}
void Editor::applyPoses(const std::vector<EditPose> &poses) {
    // Complete preflight before modifying any member of a bulk operation.
    for (const auto &p : poses) validate(p);
    std::set<void *> batches, roomBodies;
    for (const auto &p : poses) {
        if (p.target.kind == Selection::Body) {
            applyBody(bodies.at(p.target.target), {state.local(p.position), p.rotation}, p.scale);
            bodies.at(p.target.target).changed = p.changed;
        } else {
            auto &segment = segments.at(p.target.target);
            auto &box = segment.boxes.at(p.target.box);
            void *body = ptr(segment.room, off::roomBody);
            Transform tr = read<Transform>(body, off::entityTransform);
            Vec3 local = tr.rotation.inverse().rotate(state.local(p.position) - tr.position);
            applyBox(segment, box, local, tr.rotation.inverse() * p.rotation, p.scale, false);
            if (!p.changed) {
                // Preserve exact captured bytes on undo/reset to the baseline.
                void *vb = at(segment.batch, off::batchVbo);
                for (int i : box.vertices)
                    write(ptr(vb, off::vboData), i * count(vb, off::vboStride), segment.originalVertices[i]);
                void *poly = at(box.shape, off::shapePoly);
                for (size_t i = 0; i < box.originalPoly.size(); ++i)
                    write(ptr(poly, 8), i * 24, box.originalPoly[i]);
                engine.polyNormals(poly, true);
                box.position = box.center;
                box.rotation = {};
                box.scale = {1, 1, 1};
            }
            box.changed = p.changed;
            batches.insert(segment.batch);
            roomBodies.insert(body);
        }
    }
    for (void *body : roomBodies) engine.bodyMass(body);
    for (void *batch : batches) upload(segments.at(batch));
    trackEdits(poses);
}
void Editor::remember(EditAction action) {
    undoStack.push_back(std::move(action));
    if (undoStack.size() > 32) undoStack.pop_front();
    redoStack.clear();
}
void Editor::selectAll(const Json &command) {
    if (!engine.playing()) throw std::runtime_error("Start a level to select its objects");
    std::string scope = command.value("scope", std::string("segment"));
    std::string kind = command.value("kind", std::string("all"));
    if (scope != "segment" && scope != "room" && scope != "loaded")
        throw std::runtime_error("Selection scope must be segment, room or loaded");
    if (kind != "all" && kind != "boxes" && kind != "bodies")
        throw std::runtime_error("Choose blocks, bodies or both");
    void *batch = (selection.kind == Selection::Box || selection.kind == Selection::SegmentMesh)
                      ? selection.target : nullptr;
    if (scope == "segment" && !batch)
        throw std::runtime_error("Tap a block or choose a segment first");
    void *room = ptr(engine.level(), off::levelCurrent);
    std::vector<Selection> next;
    int skipped = 0;
    std::set<void *> staticBodies;
    for (const auto &[p, segment] : segments) {
        staticBodies.insert(ptr(segment.room, off::roomBody));
        if (kind == "bodies" || (scope == "segment" && p != batch) ||
            (scope == "room" && segment.room != room) || !read<uint8_t>(p, off::batchLoaded)) continue;
        for (const auto &box : segment.boxes) {
            Selection target{Selection::Box, p, box.ordinal};
            if (editable(target)) next.push_back(target); else ++skipped;
        }
    }
    if (kind != "boxes" && scope != "segment")
        for (void *body : array(engine.level(), off::levelBodies)) {
            if (staticBodies.count(body)) continue;
            void *obs = ptr(body, off::entityObstacle);
            if (scope == "room" && (!obs || ptr(obs) != room)) continue;
            if (read<uint8_t>(body, 0x56) || !read<uint8_t>(body, 0x15c) || count(body, off::bodyShapes) <= 0) {
                ++skipped;
                continue;
            }
            chooseBody(body);
            next.push_back({Selection::Body, body, -1});
        }
    if (next.size() > selectionLimit) throw std::runtime_error("Select a smaller scope: limit is 4096 objects");
    selected = std::move(next);
    selection = selected.empty() ? Selection{} : selected.back();
    ++selectionRevision;
    state.message = "Selected " + std::to_string(selected.size()) + " editable objects; " +
                    std::to_string(skipped) + " inspect-only or inactive objects skipped";
    event("selection_group", {{"scope", scope}, {"kind", kind}, {"count", selected.size()}, {"skipped", skipped}});
}
Json Editor::groupInfo() {
    Json members = Json::array();
    int editCount = 0;
    for (Selection target : selected) {
        if (!live(target)) continue;
        bool canEdit = editable(target);
        editCount += canEdit;
        uint64_t id = target.kind == Selection::Body ? bodies.at(target.target).id : segments.at(target.target).id;
        Json member{{"id", id}, {"box", target.box}, {"editable", canEdit},
                    {"kind", target.kind == Selection::Body ? "body" : target.kind == Selection::Box ? "box" : "segment_mesh"}};
        if (canEdit) member["position"] = jvec(capture(target).position);
        members.push_back(std::move(member));
    }
    Bounds b = groupBounds();
    return {{"revision", selectionRevision}, {"count", members.size()}, {"editable_count", editCount},
            {"items", members}, {"pivot", b.valid() ? jvec(state.world(b.center())) : Json()},
            {"undo_count", undoStack.size()}, {"redo_count", redoStack.size()}, {"last_ray_hit_world", lastRayHit}};
}
void Editor::moveSelection(const Json &command) {
    requirePaused();
    if (command.contains("revision") && command.at("revision").get<uint64_t>() != selectionRevision)
        throw std::runtime_error("Selection changed; start the move again");
    if (selected.empty()) throw std::runtime_error("Select a block, item or group first");
    std::string gesture = command.value("gesture", std::string());
    bool merge = !gesture.empty() && !undoStack.empty() && undoStack.back().gesture == gesture &&
                 undoStack.back().revision == selectionRevision;
    EditAction action;
    if (merge) action = undoStack.back();
    else {
        for (Selection target : selected) action.before.push_back(capture(target));
        action.gesture = gesture;
        action.revision = selectionRevision;
        Bounds b = groupBounds();
        if (!b.valid()) throw std::runtime_error("Selection has no usable bounds");
        action.pivot = state.world(b.center());
        // Direct object dragging stays under the touched triangle, including
        // when it belongs to a group spanning many depths. Gizmos keep their
        // usual aggregate pivot because they do not supply a hit anchor.
        if (command.contains("screen_anchor")) action.pivot = vec(command.at("screen_anchor"));
        cameraPose(action.camera, action.cameraRotation, action.fov);
    }
    Vec3 delta;
    if (command.contains("screen")) {
        if (gesture.empty()) throw std::runtime_error("A drag requires a gesture ID");
        int axis = command.value("axis", -1);
        float aspect = command.value("aspect", 16.f/9);
        delta = dragPoint(screenRay(command.at("screen"), action, aspect), action, axis) -
                dragPoint(screenRay(command.at("screen_start"), action, aspect), action, axis);
    } else delta = vec(command.at("delta"));
    if (command.value("snap", false)) {
        float step = command.value("step", 1.f);
        if (!std::isfinite(step) || step <= 0) throw std::runtime_error("Move step must be positive");
        delta = {std::round(delta.x/step)*step, std::round(delta.y/step)*step, std::round(delta.z/step)*step};
    }
    if (!delta.finite()) throw std::runtime_error("Move delta must be finite");
    if (!merge && delta.length() < 1e-7f) return;
    action.after = action.before;
    for (auto &p : action.after) { p.position = p.position + delta; p.changed = p.changed || delta.length() > 1e-7f; }
    applyPoses(action.after);
    if (merge) { undoStack.back() = std::move(action); redoStack.clear(); }
    else remember(std::move(action));
    state.message = "Moved " + std::to_string(selected.size()) + " objects together · Undo available";
    event("objects_moved", {{"count", selected.size()}, {"delta", jvec(delta)}, {"gesture", gesture}, {"revision", selectionRevision}});
}
void Editor::resetGroup() {
    requirePaused();
    if (selected.empty()) throw std::runtime_error("Select objects to reset");
    EditAction action;
    for (Selection target : selected) action.before.push_back(capture(target));
    action.after = action.before;
    for (auto &p : action.after) {
        p.scale = {1, 1, 1}; p.changed = false;
        if (p.target.kind == Selection::Body) {
            const auto &body = bodies.at(p.target.target);
            Transform baseline = originalBodyPose(body);
            p.position = state.world(baseline.position); p.rotation = baseline.rotation;
        } else {
            const auto &s = segments.at(p.target.target);
            Transform tr = read<Transform>(ptr(s.room, off::roomBody), off::entityTransform);
            p.position = state.world(tr.position + tr.rotation.rotate(s.boxes.at(p.target.box).center));
            p.rotation = tr.rotation;
        }
    }
    applyPoses(action.after);
    remember(std::move(action));
    state.message = "Reset " + std::to_string(selected.size()) + " objects · Undo available";
}
void Editor::applyBoxEdits(const Json &command) {
    requirePaused();
    uint64_t id = command.at("id");
    Segment *segment = nullptr;
    for (auto &[batch, candidate] : segments)
        if (candidate.id == id) { segment = &candidate; break; }
    if (!segment) throw std::runtime_error("The target segment is no longer loaded");
    const Json &edits = command.at("edits");
    if (!edits.is_array() || edits.empty() || edits.size() > selectionLimit)
        throw std::runtime_error("Provide between 1 and 4096 box edits");
    Transform tr = read<Transform>(ptr(segment->room, off::roomBody), off::entityTransform);
    EditAction action;
    std::set<int> used;
    for (const auto &edit : edits) {
        int ordinal = edit.at("box");
        if (!used.insert(ordinal).second) throw std::runtime_error("A box occurs twice in this edit");
        Selection target{Selection::Box, segment->batch, ordinal};
        EditPose before = capture(target), after = before;
        Vec3 p = vec(edit.at("position"));
        p.z += segment->offset;
        after.position = state.world(tr.position + tr.rotation.rotate(p));
        after.rotation = tr.rotation * Quat::euler(vec(edit.at("rotation_degrees"))*(PI/180));
        after.scale = vec(edit.at("scale"), {1,1,1});
        after.changed = true;
        action.before.push_back(before);
        action.after.push_back(after);
    }
    applyPoses(action.after);
    selected.clear();
    for (const auto &p : action.after) selected.push_back(p.target);
    selection = selected.back();
    ++selectionRevision;
    remember(std::move(action));
    state.message = "Applied " + std::to_string(selected.size()) + " source boxes · one Undo restores the group";
    event("box_edits_applied", {{"segment", id}, {"count", selected.size()}});
}
void Editor::undo(bool redo) {
    requirePaused();
    auto &from = redo ? redoStack : undoStack;
    auto &to = redo ? undoStack : redoStack;
    if (from.empty()) throw std::runtime_error(redo ? "Nothing to redo" : "Nothing to undo");
    const auto &poses = redo ? from.back().after : from.back().before;
    applyPoses(poses);
    selected.clear();
    for (const auto &p : poses) selected.push_back(p.target);
    selection = selected.back();
    ++selectionRevision;
    to.push_back(std::move(from.back()));
    from.pop_back();
    state.message = std::string(redo ? "Redid " : "Undid ") + std::to_string(selected.size()) + " object edits";
    event(redo ? "edit_redo" : "edit_undo", {{"count", selected.size()}});
}
Json Editor::moveHandles(float aspect) {
    Json result = Json::array();
    if (!state.enabled || !state.editor || !state.frozen || selected.empty()) return result;
    for (Selection s : selected) if (!editable(s)) return result;
    Bounds b = groupBounds();
    if (!b.valid()) return result;
    Vec3 camera, pivot = state.world(b.center()); Quat rotation; float fov;
    cameraPose(camera, rotation, fov);
    float tangent = std::tan(fov*PI/360);
    auto project = [&](Vec3 p) -> Json {
        p = rotation.inverse().rotate(p-camera);
        if (p.z >= -.05f) return nullptr;
        float x = .5f + .5f*p.x/(-p.z*tangent), y = .5f-.5f*p.y*aspect/(-p.z*tangent);
        if (!std::isfinite(x) || !std::isfinite(y)) return nullptr;
        return Json::array({x,y});
    };
    Json center = project(pivot);
    if (center.is_null()) return result;
    result.push_back({{"axis", -1}, {"start", center}, {"end", center}, {"label", "Move"}, {"color", "#ffd166"}});
    float length = std::max(.1f, (pivot-camera).length()*tangent*.16f);
    const char *labels[] = {"X", "Y", "Z"}, *colors[] = {"#ff6677", "#60ef9d", "#70aaff"};
    Vec3 view = (pivot-camera).normalized();
    for (int axis = 0; axis < 3; ++axis) {
        Vec3 a = axisVector(axis);
        if (1-std::pow(view.dot(a),2) < .003f) continue;
        Json end = project(pivot+a*length);
        if (end.is_null()) continue;
        float dx=end[0].get<float>()-center[0].get<float>(), dy=end[1].get<float>()-center[1].get<float>();
        if (dx*dx+dy*dy < .0001f) continue;
        result.push_back({{"axis", axis}, {"start", center}, {"end", end}, {"label", labels[axis]}, {"color", colors[axis]}});
    }
    return result;
}
} // namespace shdev
