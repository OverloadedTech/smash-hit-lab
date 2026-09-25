package dev.smashhit;

import android.app.AlertDialog;
import android.text.InputType;
import android.view.View;
import android.widget.*;
import java.util.Locale;
import org.json.JSONArray;
import org.json.JSONObject;

/** Optional native metadata and streaming details, away from the play HUD. */
final class ResearchControls {
    private static String room(JSONObject room) {
        if (room == null) return "None";
        JSONArray batches=room.optJSONArray("batches"); int loaded=0;
        if(batches!=null)for(int i=0;i<batches.length();i++)if(batches.optJSONObject(i).optBoolean("loaded"))loaded++;
        return room.optInt("index")+" · "+room.optString("name")+" · "+loaded+" / "+(batches==null?0:batches.length())+" meshes loaded";
    }
    static void show(DevOverlay ui) {
        ScrollView scroll=new ScrollView(ui.activity);
        LinearLayout content=ui.column(); content.setPadding(ui.dp(16),0,ui.dp(16),0); scroll.addView(content);
        ui.label(content,"Player: "+ui.data.optJSONArray("player_world")+"\nCamera: "+ui.data.optJSONArray("camera_world")+
            "\nView rotation: "+ui.data.optJSONArray("camera_rotation_degrees"),12);
        ui.label(content,"Teleport / position bookmark",14);
        final boolean playerExists=ui.data.optBoolean("playing");
        Spinner target=ui.spinner(content,playerExists?new String[]{"Player","Camera"}:new String[]{"Camera"});
        EditText[] xyz=new EditText[3]; LinearLayout fields=ui.row(content);
        for(int i=0;i<3;i++){
            EditText field=new EditText(ui.activity); field.setSingleLine(true); field.setSelectAllOnFocus(true);
            field.setTextColor(android.graphics.Color.WHITE);
            field.setInputType(InputType.TYPE_CLASS_NUMBER|InputType.TYPE_NUMBER_FLAG_DECIMAL|InputType.TYPE_NUMBER_FLAG_SIGNED);
            field.setContentDescription("Teleport "+"XYZ".charAt(i)); fields.addView(field,new LinearLayout.LayoutParams(0,ui.dp(42),1)); xyz[i]=field;
        }
        java.util.concurrent.Callable<String> which=()->playerExists&&target.getSelectedItemPosition()==0?"player":"camera";
        target.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener(){
            public void onNothingSelected(AdapterView<?> parent){}
            public void onItemSelected(AdapterView<?> parent,View view,int position,long id){
                JSONArray pose=ui.data.optJSONArray(playerExists&&position==0?"player_world":"camera_world");
                for(int i=0;i<3;i++)xyz[i].setText(String.format(Locale.US,"%.3f",pose==null?0:pose.optDouble(i)));
            }
        });
        ui.button(content,"Teleport",v->{
            try{JSONArray p=new JSONArray();for(EditText f:xyz){double n=Double.parseDouble(f.getText().toString());if(!Double.isFinite(n))throw new NumberFormatException();p.put(n);}
                DevBridge.send("teleport","target",which.call(),"position",p);
            }catch(Exception e){ui.toast("Enter three valid coordinates");}
        });
        LinearLayout bookmarks=ui.row(content);
        ui.button(bookmarks,"Save position",v->{try{DevBridge.send("save_position","target",which.call());}catch(Exception e){ui.toast(e.getMessage());}});
        ui.button(bookmarks,"Restore position",v->{try{DevBridge.send("restore_position","target",which.call());}catch(Exception e){ui.toast(e.getMessage());}});
        ui.label(content,"Bookmarks last until the level is rebuilt or the app closes.",10);

        JSONObject selection=ui.data.optJSONObject("selection");
        if(selection!=null&&!selection.optString("kind").equals("none")){
            ui.label(content,"Selected object",14);
            StringBuilder facts=new StringBuilder();
            String[][] names={{"name","Object"},{"kind","Kind"},{"id","Session ID"},{"source_index","Source index"},{"room","Room ID"},
                {"parent","Parent"},{"source","Source"},{"mesh","Mesh"},{"collider","Collider"},{"persistence","Saving"},{"limitation","Limit"}};
            for(String[] pair:names)if(selection.has(pair[0])&&!selection.isNull(pair[0]))facts.append(pair[1]).append(": ").append(selection.opt(pair[0])).append('\n');
            ui.label(content,facts.toString(),11);
        }
        ui.label(content,"Streaming at this paused frame",14);
        if(!playerExists)ui.label(content,"The menu uses the native scene system; it has no gameplay room list.",11);
        else {
            ui.label(content,"Current: "+room(ui.data.optJSONObject("current_room"))+"\nNext: "+room(ui.data.optJSONObject("next_room")),12);
            for(String key:new String[]{"current_room","next_room"}){
                JSONObject r=ui.data.optJSONObject(key);if(r==null)continue;
                JSONArray batches=r.optJSONArray("batches");if(batches==null)continue;
                StringBuilder list=new StringBuilder();
                for(int i=0;i<batches.length();i++){
                    JSONObject b=batches.optJSONObject(i);
                    list.append(b.optBoolean("loaded")?b.optBoolean("submitted")?"DRAW SUBMITTED":"LOADED":"PENDING")
                        .append(" · ").append(b.optLong("id")).append(" · ").append(b.optString("path"));
                    if(b.has("world_z_bounds"))list.append("\nZ bounds: ").append(b.optJSONArray("world_z_bounds"));
                    list.append('\n');
                }
                ui.label(content,list.toString(),10);
            }
            ui.label(content,"Draw submission does not prove that a mesh is visible on screen. Turning the camera does not reload destroyed rooms.",10);
            CheckBox bounds=ui.check(content,"Show retained room bounds",value->DevBridge.send("bounds","value",value));bounds.setChecked(ui.data.optBoolean("bounds"));
            JSONArray history=ui.data.optJSONArray("unloaded_rooms");
            if(history!=null&&history.length()>0){StringBuilder list=new StringBuilder("Recently unloaded:\n");
                for(int i=Math.max(0,history.length()-8);i<history.length();i++){JSONObject r=history.optJSONObject(i);list.append(r.optInt("index")).append(" · ").append(r.optString("name")).append(" · ID ").append(r.optLong("id")).append('\n');}
                ui.label(content,list.toString(),11);
            }
        }
        final AlertDialog dialog=new AlertDialog.Builder(ui.activity).setTitle("World details").setView(scroll).setNegativeButton("Close",null).create();
        if(!ui.transitioning())ui.button(content,playerExists?"Capture transition to menu":"Capture transition into game",v->{
            ui.world.releaseAll();ui.panelOpen=false;dialog.dismiss();
            DevBridge.send("transition","target",playerExists?"menu":"game","capture",true);ui.refreshVisibility();
        });
        dialog.show();
    }
}
