#include "editor.hpp"

namespace shdev {
void Editor::pointerInput(const Json &c) {
    requirePaused();
    std::string phase = c.at("phase"), gesture = c.at("gesture");
    if (phase == "start") {
        auto before = selected;
        float x = c.at("x"), y = c.at("y"), aspect = c.at("aspect");
        if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(aspect) || aspect <= 0)
            throw std::runtime_error("Invalid pointer coordinates");
        Vec3 hit = pick(x, y, aspect, c.value("additive", false), true);
        pointerDrag = {};
        pointerDrag.gesture = gesture; pointerDrag.hit = selection;
        pointerDrag.move = editable(selection);
        for (Selection s : selected) pointerDrag.move = pointerDrag.move && editable(s);
        pointerDrag.removeOnTap = c.value("additive", false) &&
            std::find(before.begin(), before.end(), selection) != before.end();
        pointerDrag.revision = selectionRevision;
        pointerDrag.start = Json::array({x, y});
        pointerDrag.anchor = hit;
        return;
    }
    if (pointerDrag.gesture != gesture || gesture.empty()) return;
    if (phase == "cancel") {
        if (!undoStack.empty() && undoStack.back().gesture == gesture) {
            applyPoses(undoStack.back().before); undoStack.pop_back();
        }
        pointerDrag = {}; return;
    }
    if (phase != "move" && phase != "end") throw std::runtime_error("Invalid drag phase");
    if (pointerDrag.revision != selectionRevision) { pointerDrag = {}; return; }
    if (c.value("dragged", false)) {
        pointerDrag.dragged = true;
        if (pointerDrag.move) {
            moveSelection({{"gesture", gesture}, {"revision", pointerDrag.revision}, {"axis", -1},
                {"screen_start", pointerDrag.start}, {"screen", Json::array({c.at("x"), c.at("y")})},
                {"screen_anchor", jvec(pointerDrag.anchor)},
                {"aspect", c.at("aspect")}, {"snap", c.value("snap", false)}, {"step", c.value("step", 1.f)}});
        }
    }
    if (phase == "end") {
        if (!pointerDrag.dragged && pointerDrag.removeOnTap) setSelection(pointerDrag.hit, true);
        pointerDrag = {};
    }
}
void Editor::moveDepth(float amount) {
    if (!std::isfinite(amount) || std::abs(amount) > 1000) throw std::runtime_error("Invalid depth movement");
    Vec3 direction = state.rotation().rotate({0, 0, -1});
    moveSelection({{"delta", jvec(direction * amount)}});
}
}
