package dev.smashhit.testing;

import android.app.UiAutomation;
import android.graphics.Rect;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.HandlerThread;
import android.os.Looper;
import android.os.Process;
import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyCharacterMap;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.PrintWriter;
import java.lang.reflect.Method;
import java.lang.reflect.Constructor;
import org.json.JSONObject;

/** Shell-only experiment helper. It is never included in the game APK. */
public final class DevInput {
    private static Object manager;
    private static Method inject;
    private static long downTime;
    private static UiAutomation automation;

    private static String escaped(CharSequence value) {
        return value == null ? "" : value.toString().replace("&", "&amp;")
                .replace("\"", "&quot;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private static void nodeXml(AccessibilityNodeInfo node, StringBuilder xml, int depth) {
        if (depth > 64) return;
        Rect bounds = new Rect();
        node.getBoundsInScreen(bounds);
        xml.append("<node text=\"").append(escaped(node.isPassword() ? "" : node.getText()))
                .append("\" class=\"").append(escaped(node.getClassName()))
                .append("\" package=\"").append(escaped(node.getPackageName()))
                .append("\" clickable=\"").append(node.isClickable())
                .append("\" checked=\"").append(node.isChecked())
                .append("\" visible=\"").append(node.isVisibleToUser())
                .append("\" enabled=\"").append(node.isEnabled())
                .append("\" bounds=\"[").append(bounds.left).append(',').append(bounds.top)
                .append("][").append(bounds.right).append(',').append(bounds.bottom).append("]\">");
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                try { nodeXml(child, xml, depth + 1); }
                finally { child.recycle(); }
            }
        }
        xml.append("</node>");
    }

    private static String hierarchy() throws Exception {
        if (automation == null) {
            // Same shell/root UiAutomation facility used by uiautomator dump,
            // but do not require a telemetry UI to be idle for a full second.
            HandlerThread thread = new HandlerThread("shdev-ui-reader");
            thread.start();
            Class<?> connectionType = Class.forName("android.app.IUiAutomationConnection");
            Object connection = Class.forName("android.app.UiAutomationConnection")
                    .getDeclaredConstructor().newInstance();
            Constructor<?> constructor = UiAutomation.class.getDeclaredConstructor(Looper.class, connectionType);
            constructor.setAccessible(true);
            automation = (UiAutomation) constructor.newInstance(thread.getLooper(), connection);
            UiAutomation.class.getMethod("connect").invoke(automation);
        }
        AccessibilityNodeInfo root = automation.getRootInActiveWindow();
        if (root == null) throw new IllegalStateException("No active accessibility window");
        StringBuilder xml = new StringBuilder("<hierarchy>");
        try { nodeXml(root, xml, 0); }
        finally { root.recycle(); }
        return xml.append("</hierarchy>").toString();
    }

    private static boolean motion(int action, float x, float y) throws Exception {
        long now = SystemClock.uptimeMillis();
        if (action == MotionEvent.ACTION_DOWN) downTime = now;
        MotionEvent event = MotionEvent.obtain(downTime, now, action, x, y, 0);
        event.setSource(InputDevice.SOURCE_TOUCHSCREEN);
        try { return (Boolean) inject.invoke(manager, event, 2); }
        finally { event.recycle(); }
    }

    private static boolean key(int action, int code, long start) throws Exception {
        KeyEvent event = new KeyEvent(start, SystemClock.uptimeMillis(), action, code, 0, 0,
                KeyCharacterMap.VIRTUAL_KEYBOARD, 0, KeyEvent.FLAG_FROM_SYSTEM,
                InputDevice.SOURCE_KEYBOARD);
        return (Boolean) inject.invoke(manager, event, 2);
    }

    private static JSONObject execute(JSONObject command) throws Exception {
        String op = command.getString("op");
        boolean ok = true;
        String xml = null;
        int duration = Math.max(1, Math.min(10000, command.optInt("duration_ms", 350)));
        float x = (float) command.optDouble("x", 0);
        float y = (float) command.optDouble("y", 0);
        if (op.equals("tap")) {
            ok = motion(MotionEvent.ACTION_DOWN, x, y);
            Thread.sleep(duration);
            ok &= motion(MotionEvent.ACTION_UP, x, y);
        } else if (op.equals("drag")) {
            float tx = (float) command.getDouble("to_x");
            float ty = (float) command.getDouble("to_y");
            ok = motion(MotionEvent.ACTION_DOWN, x, y);
            for (int i = 1; i <= 12; i++) {
                Thread.sleep(duration / 12);
                ok &= motion(MotionEvent.ACTION_MOVE, x + (tx - x) * i / 12,
                             y + (ty - y) * i / 12);
            }
            ok &= motion(MotionEvent.ACTION_UP, tx, ty);
        } else if (op.equals("key")) {
            int code = command.getInt("code");
            long start = SystemClock.uptimeMillis();
            ok = key(KeyEvent.ACTION_DOWN, code, start);
            Thread.sleep(duration);
            ok &= key(KeyEvent.ACTION_UP, code, start);
        } else if (op.equals("hierarchy")) {
            xml = hierarchy();
        } else if (!op.equals("info")) {
            throw new IllegalArgumentException("Unknown input operation: " + op);
        }
        JSONObject result = new JSONObject().put("ok", ok).put("pid", Process.myPid())
                .put("uid", Process.myUid()).put("version", 4)
                .put("uptime_ms", SystemClock.uptimeMillis());
        if (xml != null) result.put("xml", xml);
        return result;
    }

    public static void main(String[] args) throws Exception {
        Class<?> type = Class.forName("android.hardware.input.InputManager");
        manager = type.getDeclaredMethod("getInstance").invoke(null);
        inject = type.getMethod("injectInputEvent", InputEvent.class, int.class);
        LocalServerSocket server = new LocalServerSocket("smashhit_input_lab");
        System.out.println("Input helper ready, pid " + Process.myPid());
        while (true) {
            try (LocalSocket socket = server.accept()) {
                int uid = socket.getPeerCredentials().getUid();
                if (uid != 0 && uid != 2000) continue;
                BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream()));
                PrintWriter writer = new PrintWriter(socket.getOutputStream(), true);
                JSONObject result;
                try { result = execute(new JSONObject(reader.readLine())); }
                catch (Throwable error) {
                    Throwable cause=error;while(cause.getCause()!=null)cause=cause.getCause();
                    result = new JSONObject().put("ok", false).put("error", cause.toString());
                }
                writer.println(result.toString());
            }
        }
    }
}
