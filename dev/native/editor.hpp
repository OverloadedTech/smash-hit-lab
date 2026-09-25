#pragma once
#include "state.hpp"
#include <memory>
#include <set>

namespace shdev {
struct BoxEdit {
    int ordinal = 0, sourceIndex = 0;
    void *shape = nullptr;
    Vec3 center, half;
    Vec3 position, scale{1, 1, 1};
    Quat rotation;
    bool editable = false, changed = false;
    std::vector<int> vertices;
    std::vector<Vec3> originalPoly;
    Json attributes;
};
struct Segment {
    void *batch = nullptr;
    void *room = nullptr;
    std::string source;
    uint64_t id = 0;
    float offset = 0;
    int expectedVertices = 0;
    int occurrence = 0;
    std::vector<int> owners;
    std::vector<BoxEdit> boxes;
    std::vector<Vec3> originalVertices;
    bool mapped = false;
    std::string reason;
};
struct BodyEdit {
    void *body = nullptr;
    uint64_t id = 0;
    Transform original;
    Vec3 originalWorld, scale{1, 1, 1};
    std::map<void *, std::vector<Vec3>> originalPoly;
    bool changed = false;
    Json sourceTarget;
    void *sourceRoom = nullptr;
    float sourceOffset = 0;
    Transform sourceOriginal;
};
struct Selection {
    enum Kind { None, Box, Body, SegmentMesh } kind = None;
    void *target = nullptr;
    int box = -1;
    bool operator==(const Selection &) const = default;
};
struct EditPose {
    Selection target;
    uint64_t id = 0;
    Vec3 position, scale{1, 1, 1}; // Stable world position, including origin rebasing.
    Quat rotation;
    bool changed = false;
};
struct EditAction {
    std::vector<EditPose> before, after;
    std::string gesture;
    uint64_t revision = 0;
    Vec3 pivot, camera;
    Quat cameraRotation;
    float fov = 60;
};
class Editor {
  public:
    std::map<void *, Segment> segments;
    std::map<void *, BodyEdit> bodies;
    Selection selection;
    void segmentCreated(void *room, const std::string &source, float offset,
                        const std::vector<void *> &beforeShapes,
                        const std::vector<void *> &beforeBatches, int beforeDefinitions);
    void batchLoaded(void *batch);
    void roomDestroyed(void *room);
    void entityDestroyed(void *entity);
    void clear();
    Vec3 pick(float x, float y, float aspect, bool additive = false, bool preserveGroup = false);
    bool selectId(uint64_t id, int box = -1, bool additive = false);
    void clearSelection();
    void selectAll(const Json &command);
    Json groupInfo();
    Json moveHandles(float aspect);
    void moveSelection(const Json &command);
    void applyBoxEdits(const Json &command);
    void resetGroup();
    void undo(bool redo = false);
    Bounds groupBounds();
    Json info();
    Json objects();
    Json lines(float aspect);
    Bounds selectedBounds();
    void transform(const Json &command);
    void resetSelected();
    void reloadSection();
    void exportEdits();
    void loadSaved();
    void saveChanges();
    void forgetSaved();
    Json savedInfo();
    void obstacleCreated(void *room, void *obstacle, const Transform *definitionTransform);
    void pointerInput(const Json &command);
    void moveDepth(float amount);

  private:
    std::vector<Selection> selected;
    uint64_t selectionRevision = 0;
    std::deque<EditAction> undoStack, redoStack;
    Json lastRayHit;
    struct DefinitionSource { Json target; float offset = 0; };
    std::map<void *, std::map<int, DefinitionSource>> definitionSources;
    Json savedRecords = Json::object(), pendingRecords = Json::object();
    std::set<uint64_t> unsavableChanges;
    std::string savedError;
    uint64_t savedApplied = 0, savedSkipped = 0, saveCount = 0;
    struct PointerDrag {
        std::string gesture;
        bool move = false, dragged = false, removeOnTap = false;
        Selection hit;
        uint64_t revision = 0;
        Json start;
        Vec3 anchor;
    } pointerDrag;
    Json segmentTarget(const Segment &segment);
    Json savedRecord(Selection target);
    Transform originalBodyPose(const BodyEdit &body);
    void trackEdits(const std::vector<EditPose> &poses);
    void applySavedBatch(Segment &segment);
    void applySavedBody(BodyEdit &body);
    void setSelection(Selection target, bool additive);
    void discardTarget(void *target);
    void invalidateHistory(void *target);
    bool live(Selection target) const;
    bool editable(Selection target) const;
    Bounds boundsFor(Selection target);
    EditPose capture(Selection target);
    void validate(const EditPose &pose);
    void applyPoses(const std::vector<EditPose> &poses);
    void remember(EditAction action);
    void requirePaused() const;
    void applyBox(Segment &segment, BoxEdit &box, Vec3 position, Quat rotation, Vec3 scale,
                  bool flush = true);
    void applyBody(BodyEdit &body, Transform transform, Vec3 scale);
    void chooseBody(void *body);
    void upload(Segment &segment);
};
extern Editor editor;
} // namespace shdev
