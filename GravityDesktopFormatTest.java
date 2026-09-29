import java.util.ArrayList;
import java.util.List;

/**
 * Resolution picker: 360p / 1080p / 2160p. Never claim 4K when only 360p combined exists.
 */
public class GravityDesktopFormatTest {
    private static int failed = 0;

    public static void main(String[] args) {
        if (Sigma9.sigma() != 9 || Sigma9.PROLOGUE.length != 9) {
            fail("sigma-9");
        } else {
            ok("sigma " + Sigma9.formula());
        }
        pick360pCombined();
        pick1080pNot360p();
        pick2160pHighestBitrateHttps();
        pick2160pFallsBackTo1080p();
        pick1080pFallsBackTo360p();
        skipStoryboards();
        skipHlsWhenHttpsDashExists();
        gifUnchanged();
        genericHonorsTargetHeight();
        emptyListFallbackContainsTarget();
        youtubeClientsExposeDash();
        if (failed > 0) {
            System.err.println(failed + " failed");
            System.exit(1);
        }
        System.out.println("GravityDesktopFormatTest: all passed");
    }

    /** Real YouTube table: web client only has 18; DASH clients add 137/313/401. */
    private static List<String> youtubeDash() {
        return table(
            "sb0 mhtml 320x180      1    |                mhtml | images                    storyboard",
            "18  mp4   640x360     24  2 |  21.31MiB  730k https | avc1.42001E mp4a.40.2 44k 360p",
            "134 mp4   640x360     24    |  16.34MiB  560k https | avc1.4d401e     560k video only",
            "137 mp4   1920x1080   24    | 113.97MiB 3906k https | avc1.640028    3906k video only",
            "270 mp4   1920x1080   24    | ~137.31MiB 4701k m3u8  | avc1.640028    4701k video only",
            "248 webm  1920x1080   24    |  76.83MiB 2633k https | vp9            2633k video only",
            "313 webm  3840x2160   24    | 491.18MiB 16835k https | vp9           16835k video only",
            "401 mp4   3840x2160   24    | 316.03MiB 10832k https | av01.0.12M.08 10832k video only",
            "625 mp4   3840x2160   24    | ~569.44MiB 19497k m3u8  | vp09.00.50.08 19497k video only",
            "140 m4a   audio only      2 |   3.00MiB  129k https | audio only          mp4a.40.2  129k 44k"
        );
    }

    private static void pick360pCombined() {
        eq("360p uses combined H.264", "18",
            GravityDesktop.selectFormatFromList(youtubeDash(), false, false, 360));
    }

    private static void pick1080pNot360p() {
        eq("1080p must not pick 360p combined", "137+140",
            GravityDesktop.selectFormatFromList(youtubeDash(), false, false, 1080));
    }

    private static void pick2160pHighestBitrateHttps() {
        eq("2160p prefers VP9 https over lower-bitrate AV1 and HLS", "313+140",
            GravityDesktop.selectFormatFromList(youtubeDash(), false, false, 2160));
    }

    private static void pick2160pFallsBackTo1080p() {
        String got = GravityDesktop.selectFormatFromList(table(
            "18  mp4   640x360     24  2 |  21.31MiB  730k https | avc1.42001E mp4a.40.2 44k 360p",
            "137 mp4   1920x1080   24    | 113.97MiB 3906k https | avc1.640028    3906k video only",
            "140 m4a   audio only      2 |   3.00MiB  129k https | audio only          mp4a.40.2"
        ), false, false, 2160);
        eq("2160p request falls back to 1080p DASH, not 360p", "137+140", got);
    }

    private static void pick1080pFallsBackTo360p() {
        eq("1080p request falls back to 360p when that is all", "18",
            GravityDesktop.selectFormatFromList(table(
                "18  mp4   640x360     24  2 |  21.31MiB  730k https | avc1.42001E mp4a.40.2 44k 360p"
            ), false, false, 1080));
    }

    private static void skipStoryboards() {
        String got = GravityDesktop.selectFormatFromList(table(
            "sb0 mhtml 320x180      1    |                mhtml | images                    storyboard",
            "18  mp4   640x360     24  2 |  21.31MiB  730k https | avc1.42001E mp4a.40.2 44k 360p"
        ), false, false, 360);
        eq("storyboard mhtml is not a video format", "18", got);
    }

    private static void skipHlsWhenHttpsDashExists() {
        eq("https DASH 1080p beats higher-tbr HLS", "137+140",
            GravityDesktop.selectFormatFromList(youtubeDash(), false, false, 1080));
    }

    private static void gifUnchanged() {
        eq("GIF mode still picks gif", "gif",
            GravityDesktop.selectFormatFromList(table(
                "gif gif  480x270        |   1.00MiB https | gif",
                "401 mp4   3840x2160   24 |  60.00MiB 6000k https | av01.0.12M.08  6000k video only"
            ), true, false, 2160));
    }

    private static void genericHonorsTargetHeight() {
        List<String> rows = table(
            "sd mp4   1280x720    30 |  10.00MiB 1000k https | avc1 video only",
            "hd mp4   1920x1080   30 |  40.00MiB 4000k https | avc1 video only",
            "uhd mp4  3840x2160   30 |  80.00MiB 8000k https | avc1 video only",
            "aud m4a  audio only     |   3.00MiB  129k https | audio only mp4a.40.2"
        );
        eq("generic 2160p picks 2160", "uhd+aud",
            GravityDesktop.selectFormatFromList(rows, false, true, 2160));
        eq("generic 1080p does not exceed 1080", "hd+aud",
            GravityDesktop.selectFormatFromList(rows, false, true, 1080));
        eq("generic 360p stays at or below 360 if possible, else lowest", "sd+aud",
            GravityDesktop.selectFormatFromList(rows, false, true, 360));
    }

    private static void emptyListFallbackContainsTarget() {
        String uhd = GravityDesktop.selectFormatFromList(table(), false, false, 2160);
        if (uhd == null || !uhd.contains("height=2160")) {
            fail("2160p empty fallback should request height=2160, got: " + uhd);
        } else {
            ok("2160p empty fallback requests height=2160");
        }
        String hd = GravityDesktop.selectFormatFromList(table(), false, false, 1080);
        if (hd == null || !hd.contains("height=1080") || hd.contains("height=2160")) {
            fail("1080p empty fallback should request height=1080 only, got: " + hd);
        } else {
            ok("1080p empty fallback requests height=1080");
        }
        String sd = GravityDesktop.selectFormatFromList(table(), false, false, 360);
        if (sd == null || !sd.contains("height<=360")) {
            fail("360p empty fallback should cap height<=360, got: " + sd);
        } else {
            ok("360p empty fallback caps height<=360");
        }
    }

    private static void youtubeClientsExposeDash() {
        String args = GravityDesktop.youtubePlayerClientArgs();
        if (args == null || !args.contains("tv_embedded") || !args.contains("android_sdkless")) {
            fail("YouTube clients must include tv_embedded+android_sdkless for DASH 1080/2160, got: " + args);
        } else if (args.startsWith("youtube:player_client=web")) {
            fail("web-first clients only list 360p combined: " + args);
        } else {
            ok("YouTube clients expose DASH (tv_embedded, android_sdkless)");
        }
    }

    private static List<String> table(String... rows) {
        List<String> lines = new ArrayList<String>();
        lines.add("[info] Available formats for TESTID:");
        lines.add("ID  EXT   RESOLUTION FPS | FILESIZE   TBR PROTO | VCODEC MORE INFO");
        lines.add("-----------------------------------------------------------------");
        for (String row : rows) lines.add(row);
        return lines;
    }

    private static void eq(String name, String expected, String actual) {
        if (expected.equals(actual)) {
            ok(name);
        } else {
            fail(name + " expected=" + expected + " actual=" + actual);
        }
    }

    private static void ok(String name) {
        System.out.println("ok  " + name);
    }

    private static void fail(String msg) {
        failed++;
        System.err.println("FAIL " + msg);
    }
}
