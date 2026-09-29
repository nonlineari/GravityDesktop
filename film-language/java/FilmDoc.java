import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;

/** Lean sidecar reader for gravity.film-language.v1 — no JSON library. */
final class FilmDoc {
    String source = "";
    String raw = "{}";
    float[] fftIn = new float[0];
    float[] fftOut = new float[0];
    double epsilonSec;
    double duration;
    String[] roles = new String[0];
    double[] vertT = new double[0];
    int shots;

    static FilmDoc load(Path p) throws Exception {
        FilmDoc d = new FilmDoc();
        d.raw = Files.readString(p, StandardCharsets.UTF_8);
        d.source = str(d.raw, "source");
        d.fftIn = floats(d.raw, "fft_in");
        d.fftOut = floats(d.raw, "fft_out");
        if (d.fftOut.length == 0) d.fftOut = d.fftIn;
        d.epsilonSec = num(d.raw, "epsilon_sec");
        d.roles = firstRoles(d.raw, 6);
        d.vertT = vertexTimes(d.raw);
        d.shots = count(d.raw, "\"glyph\"");
        d.duration = lastT1(d.raw);
        return d;
    }

    static String str(String json, String key) {
        String mark = "\"" + key + "\":";
        int i = json.indexOf(mark);
        if (i < 0) return "";
        int q1 = json.indexOf('"', i + mark.length());
        if (q1 < 0) return "";
        int q2 = json.indexOf('"', q1 + 1);
        if (q2 < 0) return "";
        return json.substring(q1 + 1, q2);
    }

    static double num(String json, String key) {
        String mark = "\"" + key + "\":";
        int i = json.indexOf(mark);
        if (i < 0) return 0;
        int a = i + mark.length();
        while (a < json.length() && (json.charAt(a) == ' ' || json.charAt(a) == '\n')) a++;
        int b = a;
        while (b < json.length()) {
            char c = json.charAt(b);
            if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') b++;
            else break;
        }
        try { return Double.parseDouble(json.substring(a, b)); } catch (Exception e) { return 0; }
    }

    static float[] floats(String json, String key) {
        String mark = "\"" + key + "\":[";
        int i = json.indexOf(mark);
        if (i < 0) return new float[0];
        int a = i + mark.length();
        int b = json.indexOf(']', a);
        if (b < 0) return new float[0];
        String[] parts = json.substring(a, b).split(",");
        float[] out = new float[parts.length];
        int n = 0;
        for (String p : parts) {
            p = p.trim();
            if (p.isEmpty()) continue;
            try { out[n++] = Float.parseFloat(p); } catch (NumberFormatException ignored) {}
        }
        if (n == out.length) return out;
        float[] slim = new float[n];
        System.arraycopy(out, 0, slim, 0, n);
        return slim;
    }

    static String[] strList(String json, String key) {
        List<String> xs = new ArrayList<>();
        String mark = "\"" + key + "\":";
        int from = 0;
        while (true) {
            int i = json.indexOf(mark, from);
            if (i < 0) break;
            int q1 = json.indexOf('"', i + mark.length());
            if (q1 < 0) break;
            int q2 = json.indexOf('"', q1 + 1);
            if (q2 < 0) break;
            xs.add(json.substring(q1 + 1, q2));
            from = q2 + 1;
        }
        return xs.toArray(new String[0]);
    }

    static String[] firstRoles(String json, int n) {
        String[] all = strList(json, "role");
        if (all.length <= n) return all;
        String[] out = new String[n];
        System.arraycopy(all, 0, out, 0, n);
        return out;
    }

    /** Times from the vertices array only — not t0/t1 on shots. */
    static double[] vertexTimes(String json) {
        int i = json.indexOf("\"vertices\"");
        if (i < 0) return new double[0];
        int a = json.indexOf('[', i);
        int b = json.indexOf(']', a);
        if (a < 0 || b < 0) return new double[0];
        return nums(json.substring(a, b + 1), "\"t\":");
    }

    static double[] nums(String json, String mark) {
        List<Double> xs = new ArrayList<>();
        int from = 0;
        while (true) {
            int i = json.indexOf(mark, from);
            if (i < 0) break;
            int a = i + mark.length();
            while (a < json.length() && json.charAt(a) == ' ') a++;
            int b = a;
            while (b < json.length()) {
                char c = json.charAt(b);
                if ((c >= '0' && c <= '9') || c == '-' || c == '.' || c == 'e' || c == 'E') b++;
                else break;
            }
            try { xs.add(Double.parseDouble(json.substring(a, b))); } catch (Exception ignored) {}
            from = Math.max(b, i + 1);
        }
        double[] out = new double[xs.size()];
        for (int i = 0; i < xs.size(); i++) out[i] = xs.get(i);
        return out;
    }

    static int count(String json, String mark) {
        int n = 0, from = 0;
        while (true) {
            int i = json.indexOf(mark, from);
            if (i < 0) return n;
            n++;
            from = i + mark.length();
        }
    }

    static double lastT1(String json) {
        double last = 0;
        int from = 0;
        String mark = "\"t1\":";
        while (true) {
            int i = json.indexOf(mark, from);
            if (i < 0) return last;
            int a = i + mark.length();
            while (a < json.length() && json.charAt(a) == ' ') a++;
            int b = a;
            while (b < json.length()) {
                char c = json.charAt(b);
                if ((c >= '0' && c <= '9') || c == '-' || c == '.') b++;
                else break;
            }
            try { last = Double.parseDouble(json.substring(a, b)); } catch (Exception ignored) {}
            from = b;
        }
    }
}
