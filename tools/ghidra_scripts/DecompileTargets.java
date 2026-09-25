// Export evidence from the original native library. Run as a Ghidra postScript.
// @category SmashHit
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.symbol.Reference;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.regex.Pattern;

public class DecompileTargets extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Path out = Paths.get(args[0]);
        Files.createDirectories(out);
        String regex = args.length > 1 ? args[1] : "^(Level|Room|Segment|RenderBatch|RenderLevel|Body|Shape|Entity|Obstacle|Physics|QiViewport|Game|Renderer|ResMan|QiMesh|QiScript|LevelScript|Script|Scene|QiString|QiInput|QiVertexBuffer|QiIndexBuffer|QiRenderer|Resource|ModelBody|Ball)::.*";
        Pattern pattern = Pattern.compile(regex);
        DecompInterface decompiler = new DecompInterface();
        decompiler.openProgram(currentProgram);
        try (PrintWriter index = new PrintWriter(Files.newBufferedWriter(out.resolve("index.tsv"), StandardCharsets.UTF_8))) {
            FunctionIterator functions = currentProgram.getFunctionManager().getFunctions(true);
            while (functions.hasNext() && !monitor.isCancelled()) {
                Function f = functions.next();
                String name = f.getName(true);
                if (f.isThunk() || !pattern.matcher(name).matches()) continue;
                String file = f.getEntryPoint() + "_" + name.replaceAll("[^a-zA-Z0-9_-]", "_") + ".c";
                if (file.length() > 200) file = f.getEntryPoint() + ".c";
                DecompileResults result = decompiler.decompileFunction(f, 90, monitor);
                if (result.decompileCompleted()) {
                    String code = "// ORIGINAL BINARY DECOMPILATION. Not reconstructed source.\n// " + f.getEntryPoint() + " " + f.getSignature() + "\n" + result.getDecompiledFunction().getC();
                    Files.writeString(out.resolve(file), code);
                    index.println(f.getEntryPoint() + "\t" + name + "\t" + file);
                    index.flush();
                } else {
                    println("Failed: " + name + ": " + result.getErrorMessage());
                }
            }
        }
        decompiler.dispose();
        println("Exported decompilations to " + out);
    }
}
