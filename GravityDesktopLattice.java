import javax.swing.DefaultListModel;
import javax.swing.JFileChooser;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JMenu;
import javax.swing.JMenuItem;
import javax.swing.JPanel;
import javax.swing.JPopupMenu;
import javax.swing.JScrollPane;
import javax.swing.ListSelectionModel;
import javax.swing.SwingUtilities;
import javax.swing.Timer;
import javax.swing.WindowConstants;
import javax.swing.border.EmptyBorder;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Font;
import java.awt.event.MouseAdapter;
import java.awt.event.MouseEvent;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * GravityDesktop unique subversion: lattice-dat connector.
 * Does not replace GravityDesktop.java.
 * Right-click = sources-locator + operators-selector (DEMO video/audio).
 */
public final class GravityDesktopLattice extends JFrame {
    static final Color BG = new Color(0x0d0f12);
    static final Color INK = new Color(0xe8ecf1);
    static final Color MUTED = new Color(0x8b95a5);
    static final Color ACCENT = new Color(0x5ad0c8);

    private final DefaultListModel<Source> sources = new DefaultListModel<>();
    private final JList<Source> list = new JList<>(sources);
    private final JLabel status = new JLabel("right-click: sources locator · operators selector");
    private final Path latticeJar = Path.of(System.getProperty("user.home"),
            "Downloads/lattice-dat/java/lattice-transport.jar");
    private final Path session = Path.of(System.getProperty("user.home"),
            "Downloads/lattice-dat/sessions/preview-armature");
    private final Path cim = Path.of(System.getProperty("user.home"),
            "Downloads/nls-theformat-cim/cim/data/theformat.cim.json");
    private final Path recIndex = Path.of(System.getProperty("user.home"),
            "Downloads/GravityDesktop/REC-SAVED.json");
    private final Path extraRootsFile = Path.of(System.getProperty("user.home"),
            ".config/gravity-desktop/lattice-source-roots.txt");
    private long recIndexMtime;

    GravityDesktopLattice() {
        super("GravityDesktop · lattice subversion · sigma " + Sigma9.formula());
        setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        getContentPane().setBackground(BG);
        setLayout(new BorderLayout(8, 8));
        ((JPanel) getContentPane()).setBorder(new EmptyBorder(10, 12, 10, 12));

        if (Sigma9.sigma() != 9) throw new IllegalStateException("sigma");
        JLabel head = new JLabel("GravityDesktopLattice  ·  sigma " + Sigma9.formula() + "  ·  lattice-dat");
        head.setForeground(INK);
        head.setFont(new Font("SansSerif", Font.BOLD, 15));
        add(head, BorderLayout.NORTH);

        list.setBackground(new Color(0x161a20));
        list.setForeground(INK);
        list.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        list.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
        JScrollPane sp = new JScrollPane(list);
        sp.getViewport().setBackground(new Color(0x161a20));

        JLabel hint = new JLabel("<html>Right-click a row = send that file to DEMO / LOAD / CRT.<br>"
                + "Right-click empty space = operators selector (PLAY REC STOP DEMO LIVE MIX).</html>");
        hint.setForeground(MUTED);
        JPanel center = new JPanel(new BorderLayout(6, 6));
        center.setOpaque(false);
        center.add(sp, BorderLayout.CENTER);
        center.add(hint, BorderLayout.SOUTH);
        add(center, BorderLayout.CENTER);

        status.setForeground(ACCENT);
        status.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
        add(status, BorderLayout.SOUTH);

        MouseAdapter right = new MouseAdapter() {
            @Override public void mousePressed(MouseEvent e) { if (e.isPopupTrigger()) showMenu(e); }
            @Override public void mouseReleased(MouseEvent e) { if (e.isPopupTrigger()) showMenu(e); }
        };
        list.addMouseListener(right);
        getContentPane().addMouseListener(right);
        sp.addMouseListener(right);

        setSize(780, 520);
        setLocation(80, 80);
        refreshSources();
        new Timer(4000, e -> {
            long m = recIndex.toFile().isFile() ? recIndex.toFile().lastModified() : 0;
            if (m != recIndexMtime) refreshSources();
        }).start();
    }

    void showMenu(MouseEvent e) {
        int idx = list.locationToIndex(e.getPoint());
        Source hit = null;
        if (idx >= 0 && list.getCellBounds(idx, idx) != null
                && list.getCellBounds(idx, idx).contains(e.getPoint())) {
            list.setSelectedIndex(idx);
            hit = sources.get(idx);
        }
        final Source src = hit;
        JPopupMenu pop = new JPopupMenu();
        JMenu loc = new JMenu("Sources locator");
        loc.add(item("Refresh scan (Gravity recs + drives)", this::refreshSources));
        loc.add(item("Add folder / drive…", this::browseFolder));
        loc.add(item("Add file…", this::browseFile));
        if (src != null) {
            loc.addSeparator();
            loc.add(item("Locate " + src.name, () -> status.setText("locate " + src.file.getAbsolutePath())));
        }
        pop.add(loc);

        JMenu ops = new JMenu("Operators selector");
        ops.add(item("FILM ← this video/audio", () -> sendFilm(src)));
        ops.add(item("DEMO ← this video/audio", () -> send("demo", src)));
        ops.add(item("LOAD ← this audio", () -> send("load", src)));
        ops.add(item("CRT VIDEO ← this video", () -> send("crt", src)));
        ops.addSeparator();
        ops.add(item("LIVE  (mic REC source)", () -> launchLattice("preview", null, "LIVE")));
        ops.add(item("MIX   (tape+mic)", () -> launchLattice("preview", src, "MIX")));
        ops.add(item("PLAY lattice-dat", () -> launchLattice("preview", src, null)));
        ops.add(item("REC then lattice-dat", () -> launchLattice("preview", src, "REC")));
        ops.add(item("DEMOSCENE", () -> launchLattice("demo", src, null)));
        ops.addSeparator();
        ops.add(item("Open GravityDesktop (main)", this::launchGravityDesktop));
        pop.add(ops);
        pop.show(e.getComponent(), e.getX(), e.getY());
    }

    void sendFilm(Source src) {
        if (src == null) {
            status.setText("pick a source first (left-click a row, then right-click)");
            return;
        }
        Path film = Path.of(System.getProperty("user.home"), "Downloads/GravityDesktop/film-language");
        Path indexer = film.resolve("py/indexer.py");
        if (!Files.isRegularFile(indexer)) {
            status.setText("missing " + indexer);
            return;
        }
        try {
            List<String> args = new ArrayList<>();
            args.add("python3");
            args.add(indexer.toString());
            args.add("--file");
            args.add(src.file.getAbsolutePath());
            ProcessBuilder pb = new ProcessBuilder(args);
            pb.environment().put("PYTHONPATH", film.resolve("py").toString());
            pb.environment().put("DISPLAY", System.getenv().getOrDefault("DISPLAY", ":0.0"));
            pb.redirectErrorStream(true);
            pb.start();
            Path emp = film.resolve("qt/emp_armature.py");
            if (Files.isRegularFile(emp)) {
                ProcessBuilder q = new ProcessBuilder("python3", emp.toString());
                q.environment().put("PYTHONPATH",
                        film.resolve("py") + java.io.File.pathSeparator + film.resolve("qt"));
                q.environment().put("DISPLAY", System.getenv().getOrDefault("DISPLAY", ":0.0"));
                q.start();
            }
            status.setText("FILM index ← " + src.name);
        } catch (Exception ex) {
            status.setText("FILM: " + ex.getMessage());
        }
    }

    void send(String op, Source src) {
        if (src == null) {
            status.setText("pick a source first (left-click a row, then right-click)");
            return;
        }
        if ("demo".equals(op) || "crt".equals(op)) {
            launchLattice("demo", src, null);
        } else {
            launchLattice("preview", src, "LOAD");
        }
    }

    void launchLattice(String cmd, Source src, String recHint) {
        try {
            if (!Files.isRegularFile(latticeJar)) {
                status.setText("missing " + latticeJar);
                return;
            }
            List<String> args = new ArrayList<>();
            args.add("java");
            args.add("-jar");
            args.add(latticeJar.toString());
            args.add(cmd);
            File wav = src != null && src.audio ? src.file : defaultTape();
            args.add(wav.getAbsolutePath());
            args.add(cim.toString());
            args.add(session.toString());
            ProcessBuilder pb = new ProcessBuilder(args);
            pb.environment().put("DISPLAY", System.getenv().getOrDefault("DISPLAY", ":0.0"));
            if (src != null && src.video) {
                pb.environment().put("LATTICE_CRT_VIDEO", src.file.getAbsolutePath());
            }
            if (recHint != null) pb.environment().put("LATTICE_REC_SOURCE", recHint);
            pb.redirectErrorStream(true);
            pb.start();
            status.setText("lattice-dat " + cmd + (src == null ? "" : " ← " + src.name)
                    + (recHint == null ? "" : "  rec=" + recHint));
        } catch (Exception ex) {
            status.setText("launch: " + ex.getMessage());
        }
    }

    void launchGravityDesktop() {
        try {
            File app = new File(System.getProperty("user.home"), "Downloads/GravityDesktop");
            ProcessBuilder pb = new ProcessBuilder("bash", new File(app, "run.sh").getAbsolutePath());
            pb.directory(app);
            pb.environment().put("DISPLAY", System.getenv().getOrDefault("DISPLAY", ":0.0"));
            pb.start();
            status.setText("GravityDesktop main launched  ·  REC-SAVED sync on");
        } catch (Exception ex) {
            status.setText("GravityDesktop: " + ex.getMessage());
        }
    }

    File defaultTape() {
        File t = session.resolve("tape/reel_000.wav").toFile();
        if (t.isFile()) return t;
        return Path.of(System.getProperty("user.home"),
                "Downloads/lattice-dat/sessions/default/tape/reel_000.wav").toFile();
    }

    void browseFolder() {
        JFileChooser ch = new JFileChooser();
        ch.setFileSelectionMode(JFileChooser.DIRECTORIES_ONLY);
        ch.setDialogTitle("Sources locator — add folder or drive");
        if (ch.showOpenDialog(this) == JFileChooser.APPROVE_OPTION) {
            rememberRoot(ch.getSelectedFile());
            refreshSources();
        }
    }

    void browseFile() {
        JFileChooser ch = new JFileChooser();
        ch.setFileSelectionMode(JFileChooser.FILES_ONLY);
        ch.setDialogTitle("Sources locator — add video or audio");
        if (ch.showOpenDialog(this) == JFileChooser.APPROVE_OPTION) {
            File f = ch.getSelectedFile();
            boolean vid = nameIsVideo(f.getName());
            boolean aud = nameIsAudio(f.getName());
            if (!vid && !aud) {
                status.setText("not audio/video: " + f.getName());
                return;
            }
            sources.insertElementAt(new Source("picked", f.getName(), f, aud, vid), 0);
            list.setSelectedIndex(0);
            status.setText("picked " + f.getAbsolutePath());
        }
    }

    void rememberRoot(File dir) {
        try {
            Files.createDirectories(extraRootsFile.getParent());
            List<String> lines = extraRootsFile.toFile().isFile()
                    ? Files.readAllLines(extraRootsFile, StandardCharsets.UTF_8)
                    : new ArrayList<>();
            String p = dir.getAbsolutePath();
            if (!lines.contains(p)) {
                lines.add(p);
                Files.write(extraRootsFile, lines, StandardCharsets.UTF_8);
            }
        } catch (Exception ignored) {}
    }

    void refreshSources() {
        sources.clear();
        recIndexMtime = recIndex.toFile().isFile() ? recIndex.toFile().lastModified() : 0;
        File home = new File(System.getProperty("user.home"));
        File dl = new File(home, "Downloads");
        ingestRecSaved();
        addGlob(dl, "asc-rec-", ".wav", true, false, "gravity-rec");
        addGlob(dl, "asc-rec-", ".m4a", true, false, "gravity-rec");
        addGlob(dl, "direct-h264", ".mp4", false, true, "gravity-video");
        walkMedia(new File(dl, "lattice-dat/sessions"), "lattice-tape", 5, 80);
        walkMedia(new File(dl, "lattice-dat/fixtures"), "fixture", 4, 40);
        walkMedia(new File(home, "Videos"), "videos", 3, 40);
        walkMedia(new File(home, "Music"), "music", 3, 40);
        String user = System.getProperty("user.name");
        walkMedia(new File("/media/" + user), "drive", 4, 60);
        walkMedia(new File("/run/media/" + user), "drive", 4, 60);
        walkMedia(new File("/mnt"), "mnt", 3, 40);
        for (File extra : extraRoots()) {
            walkMedia(extra, "folder", 4, 80);
        }
        status.setText(sources.size() + " sources  ·  Gravity REC-SAVED sync  ·  right-click");
    }

    List<File> extraRoots() {
        List<File> out = new ArrayList<>();
        if (!extraRootsFile.toFile().isFile()) return out;
        try {
            for (String line : Files.readAllLines(extraRootsFile, StandardCharsets.UTF_8)) {
                if (line.isBlank() || line.startsWith("#")) continue;
                File f = new File(line.trim());
                if (f.isDirectory()) out.add(f);
            }
        } catch (Exception ignored) {}
        return out;
    }

    void ingestRecSaved() {
        if (!recIndex.toFile().isFile()) return;
        try {
            String j = Files.readString(recIndex, StandardCharsets.UTF_8);
            int from = 0;
            while (true) {
                int i = j.indexOf("\"path\":", from);
                if (i < 0) break;
                int q1 = j.indexOf('"', i + 7);
                int q2 = j.indexOf('"', q1 + 1);
                if (q1 < 0 || q2 < 0) break;
                File f = new File(j.substring(q1 + 1, q2));
                from = q2 + 1;
                if (!f.isFile()) continue;
                boolean aud = nameIsAudio(f.getName());
                boolean vid = nameIsVideo(f.getName());
                if (aud || vid) addUnique("gravity-index", f.getName(), f, aud, vid);
            }
        } catch (Exception ignored) {}
    }

    void walkMedia(File dir, String kind, int depth, int budget) {
        walkMedia(dir, kind, depth, new int[]{budget}, new LinkedHashSet<>());
    }

    void walkMedia(File dir, String kind, int depth, int[] budget, Set<String> seen) {
        if (dir == null || !dir.isDirectory() || depth < 0 || budget[0] <= 0) return;
        File[] kids = dir.listFiles();
        if (kids == null) return;
        Arrays.sort(kids, Comparator.comparing(File::getName));
        for (File f : kids) {
            if (budget[0] <= 0) return;
            if (f.isDirectory()) {
                if (f.getName().startsWith(".")) continue;
                walkMedia(f, kind, depth - 1, budget, seen);
            } else if (nameIsAudio(f.getName()) || nameIsVideo(f.getName())) {
                boolean aud = nameIsAudio(f.getName());
                addUnique(kind, rel(f), f, aud, nameIsVideo(f.getName()));
                budget[0]--;
            }
        }
    }

    void addUnique(String kind, String name, File f, boolean audio, boolean video) {
        String key = f.getAbsolutePath();
        for (int i = 0; i < sources.size(); i++) {
            if (sources.get(i).file.getAbsolutePath().equals(key)) return;
        }
        sources.addElement(new Source(kind, name, f, audio, video));
    }

    static boolean nameIsAudio(String n) {
        String x = n.toLowerCase();
        return x.endsWith(".wav") || x.endsWith(".m4a") || x.endsWith(".mp3")
                || x.endsWith(".flac") || x.endsWith(".ogg") || x.endsWith(".aif")
                || x.endsWith(".aiff");
    }

    static boolean nameIsVideo(String n) {
        String x = n.toLowerCase();
        return x.endsWith(".mp4") || x.endsWith(".mkv") || x.endsWith(".webm")
                || x.endsWith(".mov") || x.endsWith(".avi");
    }

    void addGlob(File dir, String prefix, String suffix, boolean audio, boolean video, String kind) {
        File[] all = dir.listFiles((d, n) -> n.startsWith(prefix) && n.endsWith(suffix));
        if (all == null) return;
        Arrays.sort(all, Comparator.comparingLong(File::lastModified).reversed());
        int n = 0;
        for (File f : all) {
            sources.addElement(new Source(kind, f.getName(), f, audio, video));
            if (++n >= 24) break;
        }
    }

    void walkWav(File dir, String kind) {
        if (dir == null || !dir.isDirectory()) return;
        File[] kids = dir.listFiles();
        if (kids == null) return;
        Arrays.sort(kids, Comparator.comparing(File::getName));
        for (File f : kids) {
            if (f.isDirectory()) walkWav(f, kind);
            else if (f.getName().endsWith(".wav")) {
                sources.addElement(new Source(kind, rel(f), f, true, false));
            }
        }
    }

    static String rel(File f) {
        String p = f.getAbsolutePath();
        int i = p.indexOf("lattice-dat");
        return i >= 0 ? p.substring(i) : f.getName();
    }

    static JMenuItem item(String label, Runnable r) {
        JMenuItem m = new JMenuItem(label);
        m.addActionListener(e -> r.run());
        return m;
    }

    static final class Source {
        final String kind, name;
        final File file;
        final boolean audio, video;
        Source(String kind, String name, File file, boolean audio, boolean video) {
            this.kind = kind;
            this.name = name;
            this.file = file;
            this.audio = audio;
            this.video = video;
        }
        @Override public String toString() {
            return String.format("%-14s %s", kind, name);
        }
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(() -> {
            GravityDesktopLattice w = new GravityDesktopLattice();
            w.setVisible(true);
        });
    }
}
