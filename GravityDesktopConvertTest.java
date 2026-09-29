import java.util.List;

/** VP9/AV1 → H.264: keep source pixels, never scale down to 1080p. */
public class GravityDesktopConvertTest {
    private static int failed = 0;

    public static void main(String[] args) {
        if (Sigma9.sigma() != 9 || !Sigma9.formula().equals("1+2+3+3=9")) {
            fail("sigma-9");
        } else {
            ok("sigma " + Sigma9.formula());
        }
        argsAreLibx264Crf19();
        argsDoNotScale();
        siblingPath();
        transcodeNeededOnlyForVp9Av1();
        audioNormParsers();
        ffmpegPeakAndLoudnessRoundTrip();
        if (failed > 0) {
            System.err.println(failed + " failed");
            System.exit(1);
        }
        System.out.println("GravityDesktopConvertTest: all passed");
    }

    private static void argsAreLibx264Crf19() {
        List<String> a = GravityDesktop.vp9ToH264Args("/in.mp4", "/out-avc.mp4");
        if (!a.contains("libx264") || !a.contains("19") || !a.contains("yuv420p")) {
            fail("expected libx264 crf 19 yuv420p, got " + a);
        } else {
            ok("libx264 crf 19 yuv420p");
        }
    }

    private static void argsDoNotScale() {
        List<String> a = GravityDesktop.vp9ToH264Args("/in.mp4", "/out-avc.mp4");
        for (int i = 0; i < a.size(); i++) {
            if ("-vf".equals(a.get(i)) || (a.get(i) != null && a.get(i).contains("scale="))) {
                fail("must not scale (would blur 4K): " + a);
                return;
            }
        }
        ok("no scale filter — keep source pixels");
    }

    private static void siblingPath() {
        eq("avc sibling",
            "/tmp/direct-h264-example-003-avc.mp4",
            GravityDesktop.h264SiblingPath("/tmp/direct-h264-example-003.mp4"));
        eq("already avc stays",
            "/tmp/x-avc.mp4",
            GravityDesktop.h264SiblingPath("/tmp/x-avc.mp4"));
    }

    private static void transcodeNeededOnlyForVp9Av1() {
        if (!GravityDesktop.isTranscodeNeeded("vp9")) fail("vp9 should convert");
        else ok("vp9 converts");
        if (!GravityDesktop.isTranscodeNeeded("vp09.00.50.08")) fail("vp09 should convert");
        else ok("vp09 converts");
        if (!GravityDesktop.isTranscodeNeeded("av01.0.12M.08")) fail("av01 should convert");
        else ok("av01 converts");
        if (GravityDesktop.isTranscodeNeeded("h264")) fail("h264 should skip");
        else ok("h264 skips");
        if (GravityDesktop.isTranscodeNeeded("avc1")) fail("avc1 should skip");
        else ok("avc1 skips");
    }

    private static void audioNormParsers() {
        Double max = GravityDesktop.parseMaxVolumeDb("n_samples: 0\nmax_volume: -12.4 dB\n");
        eq("peak gain", "volume=11.400dB", GravityDesktop.peakVolumeFilter(max));
        if (GravityDesktop.peakVolumeFilter(-1.0) != null) fail("peak at -1 dBFS should skip");
        else ok("peak at -1 dBFS skips");
        if (GravityDesktop.peakVolumeFilter(Double.NEGATIVE_INFINITY) != null) fail("silence should skip");
        else ok("silent peak skips");
        String json = "{\n"
            + "\"input_i\" : \"-20.50\",\n"
            + "\"input_tp\" : \"-4.00\",\n"
            + "\"input_lra\" : \"5.00\",\n"
            + "\"input_thresh\" : \"-31.00\",\n"
            + "\"target_offset\" : \"0.50\"\n}";
        eq("loudnorm linear",
            "loudnorm=I=-23.0:TP=-1.5:LRA=11.0:measured_I=-20.50:measured_TP=-4.00:"
                + "measured_LRA=5.00:measured_thresh=-31.00:offset=0.50:linear=true",
            GravityDesktop.loudnormLinearFilter(json));
        String held = "{\n"
            + "\"input_i\" : \"-23.10\",\n"
            + "\"input_tp\" : \"-2.00\",\n"
            + "\"input_lra\" : \"5.00\",\n"
            + "\"input_thresh\" : \"-33.10\",\n"
            + "\"target_offset\" : \"0.10\"\n}";
        if (GravityDesktop.loudnormLinearFilter(held) != null) fail("loudness at target should skip");
        else ok("loudness at -23 LUFS skips");
        if (GravityDesktop.audioNormFilter("off", json) != null) fail("off should skip");
        else ok("norm off skips");
        if (GravityDesktop.audioNormFilter("peak", "max_volume: -91.0 dB\n") == null) {
            fail("quiet peak should still gain");
        } else ok("quiet peak still gains");
    }

    private static void ffmpegPeakAndLoudnessRoundTrip() {
        if (!new java.io.File("/usr/bin/ffmpeg").canExecute()) {
            ok("ffmpeg roundtrip skipped");
            return;
        }
        java.io.File dir = new java.io.File("/tmp/gravity-norm-test");
        dir.mkdirs();
        java.io.File in = new java.io.File(dir, "quiet.wav");
        java.io.File peakOut = new java.io.File(dir, "peak.wav");
        java.io.File loudOut = new java.io.File(dir, "loud.wav");
        try {
            int gen = new ProcessBuilder("/usr/bin/ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                "-af", "volume=-20dB", "-c:a", "pcm_s24le", in.getAbsolutePath())
                .redirectError(ProcessBuilder.Redirect.DISCARD).start().waitFor();
            if (gen != 0 || !in.isFile()) { fail("could not synthesize tone"); return; }
            String detect = ffmpegText(java.util.List.of("/usr/bin/ffmpeg", "-hide_banner", "-nostats",
                "-i", in.getAbsolutePath(), "-af", "volumedetect", "-f", "null", "-"));
            String peak = GravityDesktop.audioNormFilter("peak", detect);
            if (peak == null || !peak.startsWith("volume=")) { fail("peak filter from tone: " + peak); return; }
            int enc = new ProcessBuilder("/usr/bin/ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", in.getAbsolutePath(), "-af", peak, "-c:a", "pcm_s24le", peakOut.getAbsolutePath())
                .redirectError(ProcessBuilder.Redirect.DISCARD).start().waitFor();
            if (enc != 0) { fail("peak encode"); return; }
            String again = ffmpegText(java.util.List.of("/usr/bin/ffmpeg", "-hide_banner", "-nostats",
                "-i", peakOut.getAbsolutePath(), "-af", "volumedetect", "-f", "null", "-"));
            Double got = GravityDesktop.parseMaxVolumeDb(again);
            if (got == null || Math.abs(got - GravityDesktop.NORM_PEAK_DBFS) > 0.2) {
                fail("peak landed at " + got + " dBFS");
            } else ok("peak roundtrip " + got + " dBFS");

            String measured = ffmpegText(java.util.List.of("/usr/bin/ffmpeg", "-hide_banner", "-nostats",
                "-i", in.getAbsolutePath(), "-af",
                "loudnorm=I=-23:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"));
            String loud = GravityDesktop.audioNormFilter("loudness", measured);
            if (loud == null || !loud.contains("linear=true")) { fail("loudnorm filter: " + loud); return; }
            int lenc = new ProcessBuilder("/usr/bin/ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", in.getAbsolutePath(), "-af", loud, "-c:a", "pcm_s24le", loudOut.getAbsolutePath())
                .redirectError(ProcessBuilder.Redirect.DISCARD).start().waitFor();
            if (lenc != 0) { fail("loudness encode: " + loud); return; }
            String check = ffmpegText(java.util.List.of("/usr/bin/ffmpeg", "-hide_banner", "-nostats",
                "-i", loudOut.getAbsolutePath(), "-af",
                "loudnorm=I=-23:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"));
            String outI = GravityDesktop.normJsonNumber(check, "input_i");
            if (outI == null) { fail("no input_i after loudness"); return; }
            double lufs = Double.parseDouble(outI);
            if (Math.abs(lufs - GravityDesktop.NORM_LOUDNESS_LUFS) > 0.6) {
                fail("loudness landed at " + lufs + " LUFS");
            } else ok("loudness roundtrip " + lufs + " LUFS");
        } catch (Exception ex) {
            fail("ffmpeg roundtrip " + ex.getMessage());
        }
    }

    private static String ffmpegText(java.util.List<String> cmd) throws Exception {
        Process p = new ProcessBuilder(cmd).redirectErrorStream(true).start();
        String text = new String(p.getInputStream().readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        if (p.waitFor() != 0) throw new Exception("ffmpeg exit " + p.exitValue());
        return text;
    }

    private static void eq(String name, String expected, String actual) {
        if (expected.equals(actual)) ok(name);
        else fail(name + " expected=" + expected + " actual=" + actual);
    }

    private static void ok(String name) {
        System.out.println("ok  " + name);
    }

    private static void fail(String msg) {
        failed++;
        System.err.println("FAIL " + msg);
    }
}
