package dev.smashhit;

import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RectF;
import android.util.SparseArray;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import org.json.JSONArray;
import org.json.JSONObject;

final class WorldView extends View {
    final DevOverlay ui;
    final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    final Set<Integer> keys = new HashSet<>();
    static final class Touch {
        int role;
        float x, y, startX, startY;
        boolean dragged;
        int axis;
        long revision, lastSend;
        String gesture;
        Touch(int role, float x, float y) {
            this.role = role;
            this.x = x;
            this.y = y;
            startX = x;
            startY = y;
        }
    }
    final SparseArray<Touch> touches = new SparseArray<>();
    float stickX, stickZ, vertical;
    WorldView(DevOverlay ui) {
        super(ui.getContext());
        this.ui = ui;
        setFocusableInTouchMode(true);
    }
    float dp(float x) { return ui.dp(x); }
    private void text(Canvas c, String text, float x, float y, int color, int size) {
        paint.setColor(color);
        paint.setTextSize(dp(size));
        paint.setStyle(Paint.Style.FILL);
        c.drawText(text, x, y, paint);
    }
    private JSONArray handles() {
        return ui.editControls != null && ui.editControls.handles.isChecked()
            ? ui.data.optJSONArray("move_handles") : null;
    }
    private void drawHandles(Canvas c) {
        JSONArray handles = handles();
        if (handles == null) return;
        // Draw axes first so the center dot remains easy to see and grab.
        for (int i=handles.length()-1; i>=0; --i) {
            JSONObject h = handles.optJSONObject(i);
            if (h == null) continue;
            JSONArray a = h.optJSONArray("start"), b = h.optJSONArray("end");
            if (a == null || b == null) continue;
            float ax=(float)a.optDouble(0)*getWidth(), ay=(float)a.optDouble(1)*getHeight();
            float bx=(float)b.optDouble(0)*getWidth(), by=(float)b.optDouble(1)*getHeight();
            int color=Color.parseColor(h.optString("color", "#ffd166"));
            paint.setStyle(Paint.Style.FILL);
            paint.setColor(0xcc101820); paint.setStrokeWidth(dp(6));
            c.drawLine(ax,ay,bx,by,paint);
            c.drawCircle(bx,by,dp(9),paint);
            paint.setColor(color); paint.setStrokeWidth(dp(3));
            c.drawLine(ax,ay,bx,by,paint);
            c.drawCircle(bx,by,dp(h.optInt("axis")==-1 ? 7 : 6),paint);
            if (h.optInt("axis") != -1) text(c,h.optString("label"),bx+dp(11),by+dp(4),color,12);
        }
    }
    private int hitHandle(float x, float y) {
        JSONArray handles = handles();
        if (handles == null) return -2;
        // Center gets a dedicated hit area; axis lines exclude that area.
        for (int i=0; i<handles.length(); ++i) {
            JSONObject h=handles.optJSONObject(i);
            if (h == null) continue;
            JSONArray a=h.optJSONArray("start"), b=h.optJSONArray("end");
            if (a == null || b == null) continue;
            float ax=(float)a.optDouble(0)*getWidth(), ay=(float)a.optDouble(1)*getHeight();
            float bx=(float)b.optDouble(0)*getWidth(), by=(float)b.optDouble(1)*getHeight();
            int axis=h.optInt("axis");
            if (Math.hypot(x-bx,y-by)<dp(14)) return axis;
            float dx=bx-ax, dy=by-ay, length=dx*dx+dy*dy;
            if (axis == -1 || length < 1) continue;
            float t=((x-ax)*dx+(y-ay)*dy)/length;
            if (t>.22f && t<1 && Math.hypot(x-ax-t*dx,y-ay-t*dy)<dp(10)) return axis;
        }
        return -2;
    }
    private boolean draggingObject() {
        for (int i=0;i<touches.size();i++) if(touches.valueAt(i).role==4||touches.valueAt(i).role==5)return true;
        return false;
    }
    private void directPointer(Touch t,String phase,float x,float y) {
        DevBridge.send("edit_pointer","phase",phase,"gesture",t.gesture,"x",x/getWidth(),"y",y/getHeight(),
            "aspect",(float)getWidth()/getHeight(),"additive",ui.editControls.multi.isChecked(),
            "dragged",t.dragged,"snap",ui.editControls.snap.isChecked(),"step",ui.editControls.step());
        t.lastSend=android.os.SystemClock.uptimeMillis();
    }
    private void dragObject(Touch t,float x,float y) {
        ui.editControls.drag(t.axis,t.startX/getWidth(),t.startY/getHeight(),x/getWidth(),y/getHeight(),
            (float)getWidth()/getHeight(),t.gesture,t.revision);
        t.lastSend=android.os.SystemClock.uptimeMillis();
    }
    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        if(ui.editing()){
            JSONArray lines=ui.data.optJSONArray("lines");paint.setStrokeWidth(dp(1.5f));
            if(lines!=null)for(int i=0;i<lines.length();i++){
                JSONArray l=lines.optJSONArray(i);if(l==null)continue;
                paint.setColor(Color.parseColor(l.optString(4,"#ffd166")));
                c.drawLine((float)l.optDouble(0)*getWidth(),(float)l.optDouble(1)*getHeight(),
                    (float)l.optDouble(2)*getWidth(),(float)l.optDouble(3)*getHeight(),paint);
            }
            if(!ui.lookInEditor)drawHandles(c);
        }
        if(ui.panelOpen||(!ui.playingControls()&&!ui.editing()&&!ui.exploring()))return;
        boolean playing=ui.playingControls();
        text(c,playing?"Tap to shoot · drag to look":ui.exploring()||ui.lookInEditor?"Drag to look · stick to fly":"Drag objects · Save & resume to keep changes",dp(12),dp(43),0xffdfebf0,11);
        float cx=dp(76),cy=getHeight()-dp(113),r=dp(54);
        paint.setStyle(Paint.Style.FILL);paint.setColor(0x80506570);c.drawCircle(cx,cy,r,paint);
        paint.setStyle(Paint.Style.STROKE);paint.setColor(0xff8eaebd);paint.setStrokeWidth(dp(1));c.drawCircle(cx,cy,r,paint);
        paint.setStyle(Paint.Style.FILL);paint.setColor(0xff65ddbb);c.drawCircle(cx+stickX*r,cy-stickZ*r,dp(17),paint);
        text(c,playing?"MOVE":"FLY",cx-dp(17),cy+r+dp(18),Color.WHITE,11);
        for(int i=0;i<2;i++){
            float y=getHeight()-dp(i==0?173:115);paint.setColor(0xcc294959);
            c.drawRoundRect(new RectF(dp(148),y,dp(210),y+dp(50)),dp(7),dp(7),paint);
            text(c,i==0?"UP":"DOWN",dp(i==0?168:157),y+dp(30),Color.WHITE,12);
        }
        if(playing){
            float x=getWidth()-dp(96),y=getHeight()-dp(110);
            paint.setColor(0xd028756c);c.drawRoundRect(new RectF(x,y,getWidth()-dp(12),y+dp(70)),dp(10),dp(10),paint);
            text(c,"FIRE",x+dp(23),y+dp(41),Color.WHITE,13);
            paint.setColor(0xddffffff);paint.setStrokeWidth(dp(1.5f));float mx=getWidth()/2f,my=getHeight()/2f;
            c.drawLine(mx-dp(6),my,mx+dp(6),my,paint);c.drawLine(mx,my-dp(6),mx,my+dp(6),paint);
        }
    }
    private final Runnable pulse=new Runnable(){public void run(){
        if(touches.size()==0&&keys.isEmpty())return;
        movement();ui.handler.postDelayed(this,80);
    }};
    private void movement() {
        float x=stickX+(keys.contains(KeyEvent.KEYCODE_D)?1:0)-(keys.contains(KeyEvent.KEYCODE_A)?1:0);
        float z=stickZ+(keys.contains(KeyEvent.KEYCODE_W)?1:0)-(keys.contains(KeyEvent.KEYCODE_S)?1:0);
        float y=vertical+(keys.contains(KeyEvent.KEYCODE_E)?1:0)-(keys.contains(KeyEvent.KEYCODE_Q)?1:0);
        DevBridge.send("play_move","value",new JSONArray(Arrays.asList(x,y,z)));
    }
    void releaseAll() {
        for(int i=0;i<touches.size();i++){
            Touch t=touches.valueAt(i);if(t.role==5)directPointer(t,"cancel",t.x,t.y);
        }
        touches.clear();keys.clear();stickX=stickZ=vertical=0;ui.handler.removeCallbacks(pulse);
        ui.cancelFire();
        if(ui.enabled)DevBridge.send("play_move","value",new JSONArray(Arrays.asList(0,0,0)));
    }
    @Override public boolean onTouchEvent(MotionEvent e) {
        if(ui.panelOpen||(!ui.playingControls()&&!ui.editing()&&!ui.exploring()))return true;
        int action=e.getActionMasked(),index=e.getActionIndex(),id=e.getPointerId(index);
        float x=e.getX(index),y=e.getY(index);
        if(action==MotionEvent.ACTION_DOWN||action==MotionEvent.ACTION_POINTER_DOWN){
            requestFocus();
            if(draggingObject())return true;
            int role=0,axis=ui.editing()&&!ui.lookInEditor?hitHandle(x,y):-2;
            if(axis!=-2){releaseAll();role=4;}
            else if(x<dp(140)&&y>getHeight()-dp(180)&&y<getHeight()-dp(50))role=1;
            else if(x>=dp(145)&&x<=dp(214)&&y>getHeight()-dp(175)&&y<getHeight()-dp(123))role=2;
            else if(x>=dp(145)&&x<=dp(214)&&y>getHeight()-dp(117)&&y<getHeight()-dp(62))role=3;
            else if(ui.playingControls()&&x>getWidth()-dp(100)&&y>getHeight()-dp(112)&&y<getHeight()-dp(37))role=6;
            else if(ui.editing()&&!ui.lookInEditor){releaseAll();role=5;}
            Touch t=new Touch(role,x,y);t.gesture="pointer-"+System.nanoTime();t.axis=axis;t.revision=ui.editControls.revision();
            touches.put(id,t);
            if(role==1){stickX=Math.max(-1,Math.min(1,(x-dp(76))/dp(54)));stickZ=Math.max(-1,Math.min(1,(getHeight()-dp(113)-y)/dp(54)));}
            if(role==2)vertical=1;if(role==3)vertical=-1;
            if(role==5)directPointer(t,"start",x,y);
            if(role==6)ui.fire(true,getWidth()/2f,getHeight()/2f);
            movement();ui.handler.removeCallbacks(pulse);ui.handler.postDelayed(pulse,80);invalidate();return true;
        }
        if(action==MotionEvent.ACTION_MOVE){
            for(int i=0;i<e.getPointerCount();i++){
                Touch t=touches.get(e.getPointerId(i));if(t==null)continue;
                float nx=e.getX(i),ny=e.getY(i);
                if(Math.abs(nx-t.startX)+Math.abs(ny-t.startY)>dp(7))t.dragged=true;
                if(t.role==1){stickX=Math.max(-1,Math.min(1,(nx-dp(76))/dp(54)));stickZ=Math.max(-1,Math.min(1,(getHeight()-dp(113)-ny)/dp(54)));}
                else if(t.role==4&&t.dragged&&android.os.SystemClock.uptimeMillis()-t.lastSend>=60)dragObject(t,nx,ny);
                else if(t.role==5&&t.dragged&&android.os.SystemClock.uptimeMillis()-t.lastSend>=60)directPointer(t,"move",nx,ny);
                else if(t.role==0&&t.dragged&&!draggingObject())DevBridge.send("play_look","yaw",-(nx-t.x)/dp(1)*.22f,"pitch",-(ny-t.y)/dp(1)*.22f);
                t.x=nx;t.y=ny;
            }
            if(!draggingObject())movement();invalidate();return true;
        }
        if(action==MotionEvent.ACTION_UP||action==MotionEvent.ACTION_POINTER_UP){
            Touch t=touches.get(id);
            if(t!=null){
                if(t.role==1){stickX=stickZ=0;}
                else if(t.role==2||t.role==3)vertical=0;
                else if(t.role==4&&t.dragged)dragObject(t,x,y);
                else if(t.role==5)directPointer(t,"end",x,y);
                else if(t.role==6)ui.fire(false,0,0);
                else if(t.role==0&&!t.dragged&&ui.playingControls())ui.tapShot(x,y);
                touches.remove(id);
            }
            movement();invalidate();return true;
        }
        if(action==MotionEvent.ACTION_CANCEL){releaseAll();return true;}
        return true;
    }
    boolean key(KeyEvent e) {
        int code=e.getKeyCode();boolean down=e.getAction()==KeyEvent.ACTION_DOWN;
        if(code==KeyEvent.KEYCODE_W||code==KeyEvent.KEYCODE_A||code==KeyEvent.KEYCODE_S||code==KeyEvent.KEYCODE_D||code==KeyEvent.KEYCODE_Q||code==KeyEvent.KEYCODE_E){
            if(down)keys.add(code);else keys.remove(code);movement();ui.handler.removeCallbacks(pulse);ui.handler.postDelayed(pulse,80);return true;
        }
        if(code==KeyEvent.KEYCODE_DPAD_LEFT||code==KeyEvent.KEYCODE_DPAD_RIGHT||code==KeyEvent.KEYCODE_DPAD_UP||code==KeyEvent.KEYCODE_DPAD_DOWN){
            if(down)DevBridge.send("play_look","yaw",code==KeyEvent.KEYCODE_DPAD_LEFT?3:code==KeyEvent.KEYCODE_DPAD_RIGHT?-3:0,
                "pitch",code==KeyEvent.KEYCODE_DPAD_UP?3:code==KeyEvent.KEYCODE_DPAD_DOWN?-3:0);return true;
        }
        return false;
    }
}
