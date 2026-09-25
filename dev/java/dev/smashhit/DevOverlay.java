package dev.smashhit;

import android.app.Activity;
import android.app.AlertDialog;
import android.graphics.Color;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.widget.*;
import java.util.ArrayList;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Small play HUD, direct editor, and a paused settings drawer. */
final class DevOverlay extends FrameLayout {
    final Activity activity;
    final Handler handler = new Handler(Looper.getMainLooper());
    final WorldView world;
    final EditorControls editControls;
    JSONObject data = new JSONObject();
    boolean enabled, refreshing, panelOpen, lookInEditor;
    private final String failure;
    private final LinearLayout panel, playBar, editBar, exploreBar;
    private final Button toggle, mode, stop, direction, behind, editLook, undo, redo, saveResume, resume, editEntry;
    private final TextView status, message, savedStatus;
    private final CheckBox fogPlay, fogEdit, useSaved, noclip, immortal, unlimited, automatic;
    private final ArrayList<Slider> sliders = new ArrayList<>();
    private String lastError = "";
    private long observedSaves = -1;
    private boolean nativePauseRequested;
    private boolean wasToolsPaused;
    private boolean savePending;
    private long fireDown;
    private long fireBaseline;
    private boolean firing;
    private float fireX, fireY;
    int dp(float n) { return Math.round(n * getResources().getDisplayMetrics().density); }
    static void textIfChanged(TextView view, CharSequence text) {
        if (!android.text.TextUtils.equals(view.getText(), text)) view.setText(text);
    }
    JSONObject controls() {
        JSONObject p = data.optJSONObject("play_controls");
        return p == null ? new JSONObject() : p;
    }
    boolean playingControls() { return controls().optBoolean("active"); }
    boolean editing() { return controls().optBoolean("editing"); }
    boolean exploring() { return controls().optBoolean("exploring"); }
    boolean transitioning() { return data.optString("context").equals("transition"); }
    DevOverlay(Activity activity, String failure) {
        super(activity);
        this.activity = activity; this.failure = failure;
        setClipChildren(false);
        world = new WorldView(this);
        addView(world, new LayoutParams(-1, -1));
        world.setVisibility(GONE);
        status = new TextView(activity);
        status.setTextColor(0xffffd166); status.setTextSize(11);
        status.setPadding(dp(12), dp(9), dp(8), dp(4));
        LayoutParams statusLayout = new LayoutParams(-2, -2, Gravity.TOP | Gravity.LEFT);
        addView(status, statusLayout);

        playBar = new LinearLayout(activity);
        playBar.setBackgroundColor(0xc9182733);
        LayoutParams bar = new LayoutParams(-1, dp(48), Gravity.BOTTOM);
        bar.leftMargin = dp(240); bar.rightMargin = dp(100); bar.bottomMargin = dp(5);
        addView(playBar, bar);
        mode = button(playBar, "Rails", v -> DevBridge.send("play_mode", "value", controls().optBoolean("rails") ? "free" : "rails"));
        stop = button(playBar, "Stop", v -> { world.releaseAll(); DevBridge.send("play_stop", "value", !controls().optBoolean("stopped")); });
        direction = button(playBar, "Reverse", v -> DevBridge.send("play_backward", "value", !controls().optBoolean("backward")));
        behind = button(playBar, "Look back", v -> DevBridge.send("play_face", "yaw", lookingBack() ? 0 : 180));
        button(playBar, "Speed", v -> openPanel());
        button(playBar, "Edit", v -> startEditing());

        editBar = new LinearLayout(activity);
        editBar.setBackgroundColor(0xd9182733);
        LayoutParams eb = new LayoutParams(-1, dp(48), Gravity.BOTTOM);
        eb.leftMargin = dp(240); eb.rightMargin = dp(12); eb.bottomMargin = dp(5);
        addView(editBar, eb);
        editLook = button(editBar, "Move objects", v -> { world.releaseAll(); lookInEditor = !lookInEditor; refreshVisibility(); });
        undo = button(editBar, "Undo", v -> editControlsUndo(false));
        redo = button(editBar, "Redo", v -> editControlsUndo(true));
        saveResume = button(editBar, "Save & resume", v -> {
            if (savePending) return;
            savePending = true;
            world.releaseAll(); DevBridge.send("save_level_edits", "resume", true); panelOpen = false;
        });
        button(editBar, "Resume", v -> resume());
        button(editBar, "More", v -> openPanel());

        exploreBar = new LinearLayout(activity);
        exploreBar.setBackgroundColor(0xd9182733);
        LayoutParams exploreLayout = new LayoutParams(-1, dp(48), Gravity.BOTTOM);
        exploreLayout.leftMargin = dp(240); exploreLayout.rightMargin = dp(12); exploreLayout.bottomMargin = dp(5);
        addView(exploreBar, exploreLayout);
        button(exploreBar, "Resume", v -> resume());
        button(exploreBar, "Tools", v -> openPanel());

        panel = column();
        panel.setPadding(dp(12), dp(8), dp(12), dp(8));
        panel.setBackgroundColor(0xf0192530);
        LayoutParams pp = new LayoutParams(dp(320), -1, Gravity.RIGHT);
        pp.topMargin = dp(46); pp.bottomMargin = dp(56);
        addView(panel, pp);
        label(panel, "Game paused", 16);
        message = label(panel, "Resume continues from the same position.", 11);
        message.setTextColor(0xffffd166);
        LinearLayout main = row(panel);
        resume = button(main, "Resume game", v -> resume());
        editEntry = button(main, "Edit level", v -> startEditing());
        ScrollView scroll = new ScrollView(activity);
        panel.addView(scroll, new LinearLayout.LayoutParams(-1, 0, 1));
        LinearLayout content = column(); scroll.addView(content);
        label(content, "Movement & view", 14);
        label(content, "Rails move automatically. Free move follows your stick. Stop holds your position while physics keeps running.", 11);
        sliders.add(new Slider(content, "Forward speed", "travel_speed", .25f, .25f, 99, "×"));
        sliders.add(new Slider(content, "Move / strafe speed", "move_speed", 1, 1, 39, " units/s"));
        sliders.add(new Slider(content, "Look speed", "look_speed", .25f, .25f, 15, "×"));
        label(content, "Look speed changes drag sensitivity and how quickly Look back turns.", 10);
        sliders.add(new Slider(content, "Field of view", "fov", 20, 1, 120, "°"));
        button(content, "Reset field of view", v -> DevBridge.send("control_settings", "custom_fov", false));
        fogPlay = check(content, "Fog during play", v -> setting("play_fog", v));
        fogEdit = check(content, "Fog while editing / in tools", v -> setting("edit_fog", v));
        automatic = check(content, "Show play controls on new runs", v -> setting("automatic", v));
        noclip = check(content, "Fly through walls", v -> DevBridge.send("noclip", "value", v));
        label(content, "Levels", 14);
        button(content, "Choose level / teleport…", v -> chooseLevel());
        label(content, "Keep your edits", 14);
        savedStatus = label(content, "", 11);
        useSaved = check(content, "Use saved edits on new runs", v -> setting("use_saved_edits", v));
        button(content, "Save edits for next run", v -> DevBridge.send("save_level_edits"));
        button(content, "Replay this level with saved edits", v -> replay());
        button(content, "Clear saved edits…", v -> new AlertDialog.Builder(activity)
            .setTitle("Clear saved edits?").setMessage("Future runs will use the original geometry. Current objects stay as they are until the level restarts.")
            .setPositiveButton("Clear saved edits", (d, w) -> DevBridge.send("forget_level_edits"))
            .setNegativeButton("Cancel", null).show());
        label(content, "Edit options", 14);
        editControls = new EditorControls(this, content);
        label(content, "Practice", 14);
        immortal = check(content, "Immortal", v -> DevBridge.send("immortal", "value", v));
        unlimited = check(content, "Unlimited balls", v -> DevBridge.send("unlimited_balls", "value", v));
        label(content, "Other tools", 14);
        button(content, "Position, rooms & research details", v -> showDetails());
        button(content, "Original game controls · new run", v -> new AlertDialog.Builder(activity)
            .setTitle("Start an original-controls run?")
            .setMessage("This starts a new run with the original camera and controls. Use Resume to continue at your current position.")
            .setPositiveButton("Start new run", (d, w) -> { world.releaseAll(); DevBridge.send("workspace", "value", "classic", "restart", true); panelOpen = false; })
            .setNegativeButton("Cancel", null).show());
        toggle = new Button(activity);
        toggle.setAllCaps(false); toggle.setText("Tools"); toggle.setTextColor(Color.WHITE);
        toggle.setTextSize(12); toggle.setPadding(0, 0, 0, 0);
        toggle.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff245b60));
        LayoutParams tp = new LayoutParams(dp(78), dp(42), Gravity.TOP | Gravity.RIGHT);
        addView(toggle, tp);
        toggle.setOnClickListener(v -> { if (panelOpen) closePanel(); else openPanel(); });
        refreshVisibility();
        handler.post(poll);
    }
    void setting(String key, boolean value) {
        if (!refreshing) DevBridge.send("control_settings", key, value);
    }
    void startEditing() {
        boolean inGame = data.optBoolean("playing") && !transitioning();
        world.releaseAll(); lookInEditor = !inGame; panelOpen = false;
        DevBridge.send("workspace", "value", inGame ? "edit" : "explore"); refreshVisibility();
    }
    void resume() {
        world.releaseAll(); panelOpen = false;
        DevBridge.send("workspace", "value", "resume"); refreshVisibility();
    }
    private void openPanel() {
        if (!failure.isEmpty()) { toast(failure); return; }
        world.releaseAll(); panelOpen = true;
        if (!editing()) DevBridge.send("workspace", "value", "tools");
        refreshVisibility();
    }
    private void closePanel() {
        panelOpen = false;
        if (!editing()) DevBridge.send("workspace", "value", "resume");
        refreshVisibility();
    }
    private void editControlsUndo(boolean forward) {
        world.releaseAll(); DevBridge.send(forward ? "edit_redo" : "edit_undo");
    }
    void toast(String text) { Toast.makeText(activity, text, Toast.LENGTH_LONG).show(); }
    private boolean lookingBack() {
        JSONObject p = controls();
        JSONArray r = p.optBoolean("turning") ? p.optJSONArray("turn_target_degrees") : data.optJSONArray("camera_rotation_degrees");
        return r != null && Math.cos(Math.toRadians(r.optDouble(1))) < 0;
    }
    LinearLayout column() { LinearLayout p = new LinearLayout(activity); p.setOrientation(LinearLayout.VERTICAL); return p; }
    LinearLayout row(LinearLayout parent) {
        LinearLayout p = new LinearLayout(activity); parent.addView(p, new LinearLayout.LayoutParams(-1, -2)); return p;
    }
    TextView label(LinearLayout parent, String text, int size) {
        TextView v = new TextView(activity); v.setText(text); v.setTextColor(0xffe1e9ee); v.setTextSize(size);
        v.setPadding(0, dp(5), 0, dp(5)); parent.addView(v, new LinearLayout.LayoutParams(-1, -2)); return v;
    }
    Button button(LinearLayout parent, String text, View.OnClickListener listener) {
        Button b = new Button(activity); b.setText(text); b.setAllCaps(false); b.setTextColor(Color.WHITE); b.setTextSize(11);
        b.setMinHeight(0); b.setMinimumHeight(0); b.setPadding(dp(3), dp(2), dp(3), dp(2));
        b.setBackgroundTintList(android.content.res.ColorStateList.valueOf(0xff304956)); b.setOnClickListener(listener);
        boolean horizontal = parent.getOrientation() == LinearLayout.HORIZONTAL;
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(horizontal ? 0 : -1, dp(42), horizontal ? 1 : 0);
        lp.setMargins(dp(2), dp(2), dp(2), dp(2)); parent.addView(b, lp); return b;
    }
    interface Toggle { void changed(boolean value); }
    CheckBox check(LinearLayout parent, String text, Toggle action) {
        CheckBox b = new CheckBox(activity); b.setText(text); b.setTextColor(Color.WHITE); b.setTextSize(12);
        b.setButtonTintList(android.content.res.ColorStateList.valueOf(0xff6ee1bf));
        parent.addView(b, new LinearLayout.LayoutParams(-1, dp(42)));
        b.setOnCheckedChangeListener((v, checked) -> { if (!refreshing) action.changed(checked); }); return b;
    }
    Spinner spinner(LinearLayout parent, String[] labels) {
        Spinner s = new Spinner(activity);
        s.setAdapter(new ArrayAdapter<String>(activity, android.R.layout.simple_spinner_dropdown_item, labels));
        parent.addView(s, new LinearLayout.LayoutParams(-1, dp(42))); return s;
    }
    private final class Slider {
        final TextView title; final SeekBar bar; final String label, key, suffix;
        final float start, increment; boolean tracking;
        Slider(LinearLayout parent, String label, String key, float start, float increment, int max, String suffix) {
            this.label=label; this.key=key; this.start=start; this.increment=increment; this.suffix=suffix;
            title=label(parent, label, 12); bar=new SeekBar(activity); bar.setMax(max); bar.setContentDescription(label);
            parent.addView(bar, new LinearLayout.LayoutParams(-1, dp(36)));
            bar.setOnSeekBarChangeListener(new SeekBar.OnSeekBarChangeListener() {
                public void onStartTrackingTouch(SeekBar s) { tracking=true; }
                public void onProgressChanged(SeekBar s, int value, boolean user) { if (user) show(start+increment*value); }
                public void onStopTrackingTouch(SeekBar s) {
                    tracking=false; DevBridge.send("control_settings", key, start+increment*s.getProgress());
                }
            });
        }
        void show(double v) { textIfChanged(title, label+" · "+String.format(Locale.US, "%.2f", v).replaceAll("0+$", "").replaceAll("\\.$", "")+suffix); }
        void refresh(JSONObject p) {
            if (tracking) return;
            double value=key.equals("fov") ? data.optDouble("fov_horizontal", 60) : p.optDouble(key, start);
            bar.setProgress(Math.round(((float)value-start)/increment)); show(value);
        }
    }
    void refreshVisibility() {
        boolean play=playingControls(), edit=editing();
        panel.setVisibility(panelOpen ? VISIBLE : GONE);
        playBar.setVisibility(play && !panelOpen ? VISIBLE : GONE);
        editBar.setVisibility(edit && !panelOpen ? VISIBLE : GONE);
        exploreBar.setVisibility(exploring() && !panelOpen ? VISIBLE : GONE);
        world.setVisibility(enabled ? VISIBLE : GONE);
        textIfChanged(toggle, panelOpen ? (edit ? "Editor" : "Resume") : "Tools");
        textIfChanged(editLook, lookInEditor ? "Look around" : "Move objects");
    }
    private final Runnable poll = new Runnable() {
        public void run() {
            try {
                if (failure.isEmpty()) data = new JSONObject(DevBridge.snapshot());
                boolean previous=enabled; enabled=data.optBoolean("enabled");
                if (previous && !enabled) { world.releaseAll(); panelOpen=false; }
                JSONObject p=controls(), saved=data.optJSONObject("saved_edits"), group=data.optJSONObject("selection_group");
                boolean play=p.optBoolean("active"), edit=p.optBoolean("editing");
                if (p.optBoolean("tools_paused") && !wasToolsPaused) panelOpen=true;
                wasToolsPaused=p.optBoolean("tools_paused");
                if (play && data.optBoolean("native_paused") && !nativePauseRequested) {
                    nativePauseRequested=true; openPanel();
                } else if (!play || !data.optBoolean("native_paused")) nativePauseRequested=false;
                if (saved != null) {
                    long saves=saved.optLong("saves");
                    if (observedSaves>=0 && saves>observedSaves) {
                        savePending=false;
                        toast("Saved "+saved.optInt("saved")+" edits for future runs"+
                            (saved.optInt("temporary")>0 ? " · "+saved.optInt("temporary")+" temporary items could not be saved" : ""));
                    }
                    observedSaves=saves;
                }
                String heading = edit ? "PAUSED · EDITING" : p.optBoolean("exploring") ? "PAUSED · FREE CAMERA" : p.optBoolean("tools_paused") ? "PAUSED · TOOLS"
                    : play ? (p.optBoolean("stopped") ? "STOPPED · LOOK & SHOOT" : p.optBoolean("rails") ? (p.optBoolean("backward") ? "RAILS · BACKWARD" : "RAILS · FORWARD") : "FREE MOVE") : "";
                if (edit && saved != null) heading += " · "+saved.optInt("unsaved")+" unsaved";
                textIfChanged(status, heading);
                textIfChanged(mode, p.optBoolean("rails") ? "Rails" : "Free move");
                textIfChanged(stop, p.optBoolean("stopped") ? "Move" : "Stop");
                textIfChanged(direction, p.optBoolean("backward") ? "Forward" : "Reverse");
                direction.setVisibility(p.optBoolean("rails") ? VISIBLE : GONE);
                textIfChanged(behind, lookingBack() ? "Look ahead" : "Look back");
                undo.setEnabled(group != null && group.optInt("undo_count") > 0);
                redo.setEnabled(group != null && group.optInt("redo_count") > 0);
                saveResume.setEnabled(data.optBoolean("playing") && !savePending);
                textIfChanged(resume, transitioning() ? "Resume transition" : data.optBoolean("playing") ? "Resume game" : "Resume menu");
                textIfChanged(editEntry, transitioning() ? "Explore transition" : data.optBoolean("playing") ? "Edit level" : "Explore menu");
                refreshing=true;
                fogPlay.setChecked(p.optBoolean("play_fog", true)); fogEdit.setChecked(p.optBoolean("edit_fog"));
                useSaved.setChecked(p.optBoolean("use_saved_edits", true)); automatic.setChecked(p.optBoolean("automatic", true));
                noclip.setChecked(data.optBoolean("noclip", true)); immortal.setChecked(data.optBoolean("immortal"));
                unlimited.setChecked(data.optBoolean("unlimited_balls"));
                if (panelOpen) for (Slider s : sliders) s.refresh(p);
                editControls.refresh();
                if (saved != null) textIfChanged(savedStatus, saved.optInt("saved")+" saved · "+saved.optInt("unsaved")+" unsaved"+
                    (saved.optInt("temporary") > 0 ? "\n"+saved.optInt("temporary")+" temporary items cannot be saved" : "")+
                    (saved.optString("error").isEmpty() ? "" : "\n"+saved.optString("error")));
                refreshing=false;
                String error=data.optString("error");
                textIfChanged(message, error.isEmpty() ? data.optString("message") : error);
                if (!error.isEmpty() && !error.equals(lastError)) { savePending=false; toast(error); }
                lastError=error;
                refreshVisibility(); world.invalidate();
            } catch (Exception e) { textIfChanged(message, e.toString()); }
            finally { refreshing=false; handler.postDelayed(this, 250); }
        }
    };
    private void replay() {
        JSONObject saved=data.optJSONObject("saved_edits");
        Runnable restart=() -> {
            JSONObject nav=data.optJSONObject("navigation");
            DevBridge.send("replay_level", "index", Math.max(0, nav == null ? 0 : nav.optInt("current_checkpoint")));
            panelOpen=false;
        };
        if (saved != null && saved.optInt("unsaved") > 0) {
            new AlertDialog.Builder(activity).setTitle("Save before replaying?")
                .setPositiveButton("Save & replay", (d,w) -> {
                    JSONObject nav=data.optJSONObject("navigation");
                    DevBridge.send("save_replay", "index", Math.max(0, nav == null ? 0 : nav.optInt("current_checkpoint")));
                    panelOpen=false;
                }).setNegativeButton("Cancel", null).show();
        } else restart.run();
    }
    private void chooseLevel() {
        JSONObject nav=data.optJSONObject("navigation");
        JSONArray levels=nav == null ? null : nav.optJSONArray("levels");
        if (levels == null || levels.length()==0) { toast("The level list is still loading"); return; }
        String[] labels=new String[levels.length()];
        for (int i=0;i<labels.length;i++) {
            JSONObject level=levels.optJSONObject(i);
            labels[i]=i+" · "+level.optString("name");
        }
        final int[] chosen={Math.max(0, Math.min(labels.length-1, nav.optInt("current_checkpoint")))};
        LinearLayout extras=column(); extras.setPadding(dp(12),0,dp(12),0);
        CheckBox unlock=check(extras,"Unlock all levels · this session", value -> DevBridge.send("unlock_levels","value",value));
        unlock.setChecked(nav.optBoolean("unlocked"));
        label(extras,"Enable Unlock all levels to visit checkpoints you have not reached.",11);
        CheckBox atEnd=check(extras,"Arrive at the end", value -> {});
        new AlertDialog.Builder(activity).setTitle("Choose a level")
            .setSingleChoiceItems(labels, chosen[0], (d,w) -> chosen[0]=w).setView(extras)
            .setPositiveButton("Teleport", (d,w) -> DevBridge.send("jump_level","index",chosen[0],"at_end",atEnd.isChecked()))
            .setNeutralButton("Rooms…", (d,w) -> chooseRoom(chosen[0]))
            .setNegativeButton("Cancel",null).show();
    }
    private void chooseRoom(int level) {
        JSONObject nav=data.optJSONObject("navigation"); JSONArray rooms=nav==null?null:nav.optJSONArray("rooms");
        ArrayList<String> names=new ArrayList<>(); ArrayList<Integer> ids=new ArrayList<>();
        if (rooms != null) for (int i=0;i<rooms.length();i++) {
            JSONObject r=rooms.optJSONObject(i); if (r.optInt("checkpoint") != level) continue;
            names.add(r.optString("name")); ids.add(r.optInt("index"));
        }
        if (ids.isEmpty()) { toast("Teleport into this level first to load its room list"); return; }
        new AlertDialog.Builder(activity).setTitle("Teleport to a room")
            .setItems(names.toArray(new String[0]), (d,w) -> DevBridge.send("jump_room","index",ids.get(w)))
            .setNegativeButton("Cancel",null).show();
    }
    private void showDetails() {
        ResearchControls.show(this);
    }
    private void fireEvent(int action) {
        MotionEvent event=MotionEvent.obtain(fireDown,android.os.SystemClock.uptimeMillis(),action,fireX,fireY,0);
        event.setSource(android.view.InputDevice.SOURCE_TOUCHSCREEN);
        // The shipped GameActivity.onTouchEvent directly forwards into its
        // native input queue. This preserves original shooting and powerups.
        activity.onTouchEvent(event); event.recycle();
    }
    private final Runnable releaseFire = new Runnable() {
        public void run() {
            if (!firing) return;
            if (DevBridge.shotSerial()!=fireBaseline || android.os.SystemClock.uptimeMillis()-fireDown>=1500) cancelFire();
            else handler.postDelayed(this,16);
        }
    };
    void cancelFire() {
        handler.removeCallbacks(releaseFire);
        if (firing) fireEvent(MotionEvent.ACTION_UP);
        firing=false;
    }
    void fire(boolean down, float x, float y) {
        if (!down) {
            handler.removeCallbacks(releaseFire);
            if (firing) releaseFire.run();
            return;
        }
        if (!playingControls() || panelOpen || data.optBoolean("frozen")) return;
        cancelFire();
        fireDown=android.os.SystemClock.uptimeMillis(); fireBaseline=DevBridge.shotSerial();
        fireX=x; fireY=y; firing=true;
        fireEvent(MotionEvent.ACTION_DOWN);
    }
    void tapShot(float x,float y) {
        fire(true,x,y);
        // A short tap must span the native frame that consumes it. A fixed
        // millisecond pulse can disappear between frames on a slow device.
        fire(false,x,y);
    }
    boolean handleKey(KeyEvent e) {
        if (activity.getCurrentFocus() instanceof EditText) return false;
        int key=e.getKeyCode(); boolean down=e.getAction()==KeyEvent.ACTION_DOWN;
        if (key==KeyEvent.KEYCODE_F1 || key==KeyEvent.KEYCODE_TAB || key==KeyEvent.KEYCODE_ESCAPE ||
            (key==KeyEvent.KEYCODE_BACK && (enabled || panelOpen))) {
            if (down && e.getRepeatCount()==0) { if(panelOpen)closePanel();else openPanel(); } return true;
        }
        if (!enabled || panelOpen) return false;
        if (playingControls() && (key==KeyEvent.KEYCODE_SPACE || key==KeyEvent.KEYCODE_ENTER)) {
            if (!down || e.getRepeatCount()==0) fire(down,world.getWidth()/2f,world.getHeight()/2f); return true;
        }
        if (editing() && editControls.key(e)) return true;
        return world.key(e);
    }
    @Override public void onWindowFocusChanged(boolean focused) {
        super.onWindowFocusChanged(focused);
        if (!focused && world != null) world.releaseAll();
    }
}
