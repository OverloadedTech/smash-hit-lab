package dev.smashhit;

import android.app.AlertDialog;
import android.text.InputType;
import android.view.KeyEvent;
import android.widget.*;
import java.util.Arrays;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Optional precise controls. The primary editor gesture is dragging an object. */
final class EditorControls {
    final DevOverlay ui;
    final CheckBox multi, handles, snap;
    final TextView summary;
    final Button depthNear, depthFar, exact, reset, stepButton;
    private float stepValue = 1;
    EditorControls(DevOverlay ui, LinearLayout parent) {
        this.ui=ui;
        summary=ui.label(parent,"Drag an object to move it. Use Look around to turn the camera.",12);
        multi=ui.check(parent,"Select several objects",v->{});
        handles=ui.check(parent,"Show axis handles",v->ui.world.invalidate());
        snap=ui.check(parent,"Snap moves to grid",v->{});
        LinearLayout select=ui.row(parent);
        ui.button(select,"This piece",v->sendEdit("select_all","scope","segment","kind","boxes"));
        ui.button(select,"Whole room",v->sendEdit("select_all","scope","room"));
        ui.button(select,"Clear",v->DevBridge.send("clear_selection"));
        LinearLayout depth=ui.row(parent);
        depthNear=ui.button(depth,"Closer",v->sendEdit("move_depth","amount",-stepValue));
        depthFar=ui.button(depth,"Farther",v->sendEdit("move_depth","amount",stepValue));
        stepButton=ui.button(parent,"Move step · 1",v->{
            final float[] values={.1f,.5f,1,5,10};
            new AlertDialog.Builder(ui.activity).setTitle("Move step / grid size")
                .setItems(new String[]{"0.1","0.5","1","5","10"},(d,w)->{
                    setStep(values[w]);
                }).setNegativeButton("Cancel",null).show();
        });
        LinearLayout object=ui.row(parent);
        ui.button(object,"Focus selection",v->sendEdit("focus_selection"));
        reset=ui.button(object,"Reset selected",v->sendEdit("reset_selection"));
        exact=ui.button(parent,"Position / rotation / size…",v->exactTransform());
    }
    long revision() {
        JSONObject g=ui.data.optJSONObject("selection_group"); return g==null?0:g.optLong("revision");
    }
    float step() { return stepValue; }
    private void setStep(float value) { stepValue=value; DevOverlay.textIfChanged(stepButton,"Move step · "+value); }
    void stopRepeat() {}
    void sendEdit(String operation,Object... pairs) {
        try {
            JSONObject edit=new JSONObject().put("op",operation);
            for(int i=0;i<pairs.length;i+=2) edit.put((String)pairs[i],pairs[i+1]);
            if(ui.editing()) DevBridge.command(edit.toString());
            else DevBridge.send("batch","commands",new JSONArray()
                .put(new JSONObject().put("op","workspace").put("value","edit")).put(edit));
        } catch(Exception e){ui.toast(e.getMessage());}
    }
    void move(int axis,float amount,String gesture,long revision) {
        float[] v={0,0,0};v[axis]=amount;
        sendEdit("move_selection","delta",new JSONArray(Arrays.asList(v[0],v[1],v[2])),"gesture",gesture,"revision",revision);
    }
    void drag(int axis,float sx,float sy,float x,float y,float aspect,String gesture,long revision) {
        sendEdit("move_selection","axis",axis,"screen_start",new JSONArray(Arrays.asList(sx,sy)),
            "screen",new JSONArray(Arrays.asList(x,y)),"aspect",aspect,"gesture",gesture,"revision",revision,
            "snap",snap.isChecked(),"step",step());
    }
    void refresh() {
        JSONObject g=ui.data.optJSONObject("selection_group"),o=ui.data.optJSONObject("selection");
        int n=g==null?0:g.optInt("count"), editable=g==null?0:g.optInt("editable_count");
        String title=n==0?"Drag an object to move it. Use Look around to turn the camera."
            :n==1&&o!=null?(o.optString("kind").equals("box")?"Block "+o.optInt("source_index"):o.optString("name")):n+" objects selected";
        if(n>0&&n!=editable)title+=" · some objects cannot move";
        if(n==1&&o!=null&&o.has("can_save")&&!o.optBoolean("can_save"))title+=" · current run only";
        DevOverlay.textIfChanged(summary,title);
        depthNear.setEnabled(n>0&&n==editable);depthFar.setEnabled(n>0&&n==editable);reset.setEnabled(n>0&&n==editable);
        exact.setEnabled(n==1&&editable==1);
    }
    private void exactTransform() {
        JSONObject o=ui.data.optJSONObject("selection");if(o==null)return;
        LinearLayout content=ui.column();content.setPadding(ui.dp(14),0,ui.dp(14),0);
        EditText[][] fields=new EditText[3][3];
        String[] titles={"Position X / Y / Z","Rotation X / Y / Z","Size X / Y / Z"};
        String[] keys={"position","rotation_degrees","scale_factor"};
        for(int group=0;group<3;group++){
            ui.label(content,titles[group],12);LinearLayout row=ui.row(content);JSONArray a=o.optJSONArray(keys[group]);
            for(int i=0;i<3;i++){
                EditText v=new EditText(ui.activity);v.setSingleLine(true);v.setSelectAllOnFocus(true);v.setTextColor(android.graphics.Color.WHITE);
                v.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL|InputType.TYPE_NUMBER_FLAG_SIGNED);
                v.setText(String.format(Locale.US,"%.3f",a==null?0:a.optDouble(i)));
                v.setContentDescription(titles[group]+" "+"XYZ".charAt(i));row.addView(v,new LinearLayout.LayoutParams(0,ui.dp(42),1));fields[group][i]=v;
            }
        }
        AlertDialog dialog=new AlertDialog.Builder(ui.activity).setTitle("Edit selected object").setView(content)
            .setPositiveButton("Apply",null).setNegativeButton("Cancel",null).create();
        dialog.setOnShowListener(d->dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{
            try{
                JSONArray[] values={new JSONArray(),new JSONArray(),new JSONArray()};
                for(int g=0;g<3;g++)for(EditText field:fields[g]){
                    double n=Double.parseDouble(field.getText().toString());if(!Double.isFinite(n))throw new NumberFormatException();values[g].put(n);
                }
                sendEdit("transform","position",values[0],"rotation_degrees",values[1],"scale",values[2]);dialog.dismiss();
            }catch(Exception e){ui.toast("Enter valid numbers in every field");}
        }));dialog.show();
    }
    boolean key(KeyEvent e) {
        int key=e.getKeyCode();boolean down=e.getAction()==KeyEvent.ACTION_DOWN;
        if(e.isCtrlPressed()&&(key==KeyEvent.KEYCODE_Z||key==KeyEvent.KEYCODE_Y)){
            if(down&&e.getRepeatCount()==0)sendEdit(key==KeyEvent.KEYCODE_Y||e.isShiftPressed()?"edit_redo":"edit_undo");return true;
        }
        if(e.isCtrlPressed()&&key==KeyEvent.KEYCODE_S){if(down&&e.getRepeatCount()==0)DevBridge.send("save_level_edits");return true;}
        if(e.isCtrlPressed()&&key==KeyEvent.KEYCODE_A){if(down&&e.getRepeatCount()==0)sendEdit("select_all","scope","room");return true;}
        if(ui.lookInEditor)return false;
        int axis=key==KeyEvent.KEYCODE_DPAD_LEFT||key==KeyEvent.KEYCODE_DPAD_RIGHT?0
            :key==KeyEvent.KEYCODE_PAGE_UP||key==KeyEvent.KEYCODE_PAGE_DOWN?1
            :key==KeyEvent.KEYCODE_DPAD_UP||key==KeyEvent.KEYCODE_DPAD_DOWN?2:-1;
        if(axis<0)return false;
        if(down){int sign=key==KeyEvent.KEYCODE_DPAD_LEFT||key==KeyEvent.KEYCODE_DPAD_UP||key==KeyEvent.KEYCODE_PAGE_DOWN?-1:1;
            move(axis,sign*step()*(e.isShiftPressed()?10:e.isAltPressed()?.1f:1)*(e.getRepeatCount()+1),"key-"+e.getDownTime()+"-"+key,revision());}
        return true;
    }
}
