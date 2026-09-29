/**
 * Livecode expander. GraalPy guest if polyglot is on the classpath;
 * Java fallback otherwise. Never imports numpy — ML stays in CPython py/.
 */
final class FilmLivecode {
    static final String GUEST =
            "def expand(q):\n"
            + "    ql = (q or '').lower()\n"
            + "    words = ql.replace('/', ' ').split()\n"
            + "    if ('pov' in words or 'pov' in ql) and 'yolo:' not in ql:\n"
            + "        q = (q or '') + ' yolo:POV_IMAGE'\n"
            + "    return q\n"
            + "expand(q)\n";

    static String expand(String q) {
        if (q == null) return "";
        String graal = graalExpand(q);
        if (graal != null) return graal;
        return javaExpand(q);
    }

    static String javaExpand(String q) {
        String t = q.trim();
        String low = t.toLowerCase();
        boolean pov = low.matches(".*\\bpov\\b.*");
        if (pov && !low.contains("yolo:")) t = t + " yolo:POV_IMAGE";
        return t;
    }

    static String graalExpand(String q) {
        try {
            Class<?> ctxCl = Class.forName("org.graalvm.polyglot.Context");
            Class<?> valCl = Class.forName("org.graalvm.polyglot.Value");
            Object builder = ctxCl.getMethod("newBuilder", String[].class)
                    .invoke(null, (Object) new String[]{"python"});
            builder.getClass().getMethod("allowAllAccess", boolean.class).invoke(builder, true);
            Object ctx = builder.getClass().getMethod("build").invoke(builder);
            try {
                Object bindings = ctxCl.getMethod("getBindings", String.class).invoke(ctx, "python");
                bindings.getClass().getMethod("putMember", String.class, Object.class).invoke(bindings, "q", q);
                Object val = ctxCl.getMethod("eval", String.class, CharSequence.class)
                        .invoke(ctx, "python", GUEST);
                Object out = valCl.getMethod("asString").invoke(val);
                return out == null ? q : out.toString();
            } finally {
                if (ctx instanceof AutoCloseable) ((AutoCloseable) ctx).close();
            }
        } catch (Throwable ignored) {
            return null;
        }
    }

    public static void main(String[] args) {
        String q = expand(args.length > 0 ? args[0] : "cut POV where /θ/ hits ILL(T)");
        System.out.println(q);
        if (!q.toLowerCase().contains("yolo:pov_image")) System.exit(1);
    }
}
