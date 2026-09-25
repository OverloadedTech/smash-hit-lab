package dev.smashhit;

import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.res.AssetManager;
import android.os.Build;
import android.view.KeyEvent;
import android.view.ViewGroup;
import android.widget.Toast;
import org.json.JSONObject;

/**
 * The only link injected into the original activity. Native changes are queued
 * and executed by the original game/render thread, never the Android UI thread.
 */
public final class DevBridge {
    static DevOverlay overlay;
    private static boolean loaded;
    private static String failure = "";
    public static native String init(AssetManager assets, String files);
    public static native void command(String json);
    public static native String snapshot();
    public static native long shotSerial();
    public static void prepare(Activity activity) {
        if (loaded || !failure.isEmpty())
            return;
        try {
            System.loadLibrary("shdev");
            loaded = true;
            failure = init(activity.getAssets(), activity.getFilesDir().getAbsolutePath());
        } catch (Throwable e) {
            failure = e.toString();
        }
    }
    public static void install(Activity activity) {
        if (overlay != null)
            return;
        prepare(activity);
        overlay = new DevOverlay(activity, failure);
        activity.addContentView(overlay, new ViewGroup.LayoutParams(-1, -1));
        if (loaded && failure.isEmpty()) {
            BroadcastReceiver receiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context context, Intent intent) {
                    String text = intent.getStringExtra("command");
                    if (text != null) {
                        command(text);
                        setResultData("queued");
                    }
                }
            };
            IntentFilter filter = new IntentFilter("dev.smashhit.COMMAND");
            // Shell-only laboratory automation. Ordinary applications cannot
            // send commands because android.permission.DUMP is required.
            if (Build.VERSION.SDK_INT >= 33)
                activity.registerReceiver(receiver, filter, "android.permission.DUMP", null,
                                          Context.RECEIVER_EXPORTED);
            else
                activity.registerReceiver(receiver, filter, "android.permission.DUMP", null);
        }
    }
    static void send(String op, Object... values) {
        if (!loaded)
            return;
        try {
            JSONObject c = new JSONObject();
            c.put("op", op);
            for (int i = 0; i + 1 < values.length; i += 2)
                c.put(values[i].toString(), values[i + 1]);
            command(c.toString());
        } catch (Exception e) {
            if (overlay != null)
                Toast.makeText(overlay.getContext(), e.getMessage(), Toast.LENGTH_SHORT).show();
        }
    }
    public static boolean handleKey(KeyEvent event) {
        return overlay != null && overlay.handleKey(event);
    }
}
