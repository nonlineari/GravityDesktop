import javax.swing.BorderFactory;
import javax.swing.DefaultListModel;
import javax.swing.JButton;
import javax.swing.JComponent;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JList;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JTextField;
import javax.swing.ListSelectionModel;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;
import javax.swing.Timer;
import javax.swing.WindowConstants;
import javax.swing.border.EmptyBorder;
import javax.swing.border.TitledBorder;
import java.awt.BorderLayout;
import java.awt.Color;
import java.awt.Font;
import java.awt.GridLayout;
import java.io.BufferedReader;
import java.io.File;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

/**
 * GravityDesktop unique subversion: GraalVM host + CPython lean ML env.
 * Does not replace GravityDesktop.java. Qt EMP is frozen at prototype-1.
 */
public final class GravityDesktopFilm extends JFrame {
    static final Color BG = new Color(0x0d0f12);
    static final Color INK = new Color(0xe8ecf1);
    static final Color MUTED = new Color(0x8b95a5);
    static final Color ACCENT = new Color(0x5ad0c8);
    static final Color MAGENTA = new Color(0xff3dce);

    private final DefaultListModel<String> model = new DefaultListModel<>();
    private final JList<String> list = new JList<>(model);
    private final JLabel status = new JLabel("Graal host  ·  CPython ML  ·  livecode drives Index/Search");
    private final JTextField live = new JTextField();
    private final List<File> files = new ArrayList<>();
    private final Path filmRoot;
    private final Path py;
    private final PlanPanel plan = new PlanPanel();
    private final ElevationPanel elev = new ElevationPanel();
    private final ModelPanel modelView = new ModelPanel();
    private Path currentSidecar;
    private int loopStep;
    private Timer idleClock;

    GravityDesktopFilm() {
        super("GravityDesktop Film  ·  sigma " + Sigma9.formula() + "  ·  t_loop  ·  FFF+FFT");
        Path here = Path.of(System.getProperty("user.dir"));
        Path guess = here.resolve("film-language");
        filmRoot = Files.isDirectory(guess) ? guess : here;
        py = filmRoot.resolve("py");
        setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
        getContentPane().setBackground(BG);
        setLayout(new BorderLayout(8, 8));
        ((JPanel) getContentPane()).setBorder(new EmptyBorder(10, 12, 10, 12));

        JLabel head = new JLabel("⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿰   Graal  ·  Escher wrap  ·  Duchamp stair  ·  Man Ray stills");
        head.setForeground(INK);
        head.setFont(new Font("SansSerif", Font.BOLD, 14));
        add(head, BorderLayout.NORTH);

        list.setBackground(new Color(0x161a20));
        list.setForeground(INK);
        list.setSelectionMode(ListSelectionModel.SINGLE_SELECTION);
        list.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
        list.addListSelectionListener(e -> {
            if (!e.getValueIsAdjusting()) onSelect();
        });
        JScrollPane sp = new JScrollPane(list);
        sp.setBorder(titled("AVD"));
        sp.setPreferredSize(new java.awt.Dimension(240, 200));

        JPanel emp = new JPanel(new GridLayout(1, 3, 6, 6));
        emp.setOpaque(false);
        emp.add(wrap("PLAN  timeline", plan));
        emp.add(wrap("ELEVATION  audio", elev));
        emp.add(wrap("MODEL  Operation", modelView));

        JPanel center = new JPanel(new BorderLayout(8, 8));
        center.setOpaque(false);
        center.add(sp, BorderLayout.WEST);
        center.add(emp, BorderLayout.CENTER);
        add(center, BorderLayout.CENTER);

        JPanel fn = new JPanel(new GridLayout(1, 6, 6, 6));
        fn.setOpaque(false);
        fn.add(btn("Index", this::indexSel));
        fn.add(btn("Search", this::searchSel));
        fn.add(btn("Compile", this::compileSel));
        fn.add(btn("Splice", this::spliceLast));
        fn.add(btn("Preview", this::preview));
        fn.add(btn("Loop", this::loopSel));

        live.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
        live.setBackground(new Color(0x0a0c10));
        live.setForeground(ACCENT);
        live.setCaretColor(ACCENT);
        live.setText("cut POV where /θ/ hits ILL(T)");
        live.setBorder(BorderFactory.createCompoundBorder(
                BorderFactory.createLineBorder(ACCENT),
                new EmptyBorder(4, 6, 4, 6)));
        live.addActionListener(e -> searchSel());

        JPanel liveRow = new JPanel(new BorderLayout(6, 6));
        liveRow.setOpaque(false);
        JLabel liveLbl = new JLabel("livecode");
        liveLbl.setForeground(MAGENTA);
        liveLbl.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
        liveRow.add(liveLbl, BorderLayout.WEST);
        liveRow.add(live, BorderLayout.CENTER);

        status.setForeground(ACCENT);
        status.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));

        JPanel south = new JPanel(new BorderLayout(6, 6));
        south.setOpaque(false);
        south.add(fn, BorderLayout.NORTH);
        south.add(liveRow, BorderLayout.CENTER);
        south.add(status, BorderLayout.SOUTH);
        add(south, BorderLayout.SOUTH);

        setSize(1280, 740);
        setLocation(48, 48);
        refresh();
        idleClock = new Timer(90, e -> {
            if (currentSidecar != null) return;
            loopStep = Math.floorMod(loopStep + 1, 16);
            pushLoop("IDLE");
        });
        idleClock.start();
    }

    static TitledBorder titled(String s) {
        TitledBorder t = BorderFactory.createTitledBorder(
                BorderFactory.createLineBorder(MAGENTA), s);
        t.setTitleColor(MAGENTA);
        t.setTitleFont(new Font(Font.MONOSPACED, Font.PLAIN, 11));
        return t;
    }

    static JPanel wrap(String title, JComponent c) {
        JPanel p = new JPanel(new BorderLayout());
        p.setOpaque(false);
        p.setBorder(titled(title));
        p.add(c, BorderLayout.CENTER);
        return p;
    }

    JButton btn(String label, Runnable r) {
        JButton b = new JButton(label);
        b.addActionListener(e -> r.run());
        return b;
    }

    File selected() {
        int i = list.getSelectedIndex();
        if (i < 0 || i >= files.size()) return null;
        return files.get(i);
    }

    Path sidecarOf(File f) {
        return Path.of(f.getAbsolutePath() + ".film.json");
    }

    void loadSidecar(Path side) {
        try {
            FilmDoc d = FilmDoc.load(side);
            currentSidecar = side;
            plan.setDoc(d);
            elev.setDoc(d);
            modelView.setDoc(d);
            plan.setLoop(loopStep);
            elev.setLoop(loopStep);
            modelView.setLoop(loopStep);
            modelView.setOperation(IdleSurface.op(true, loopStep));
            if (idleClock != null) idleClock.stop();
            int[] v = IdcLoop.vertex(loopStep);
            status.setText(String.format(
                    "%s  t_loop %s  FFT %d  ε %.3f ms  verts %d  shots %d  ·  %s",
                    IdcLoop.IDC, IdcLoop.bits(v),
                    d.fftIn.length, d.epsilonSec * 1000.0, d.vertT.length, d.shots, side.getFileName()));
        } catch (Exception ex) {
            status.setText("sidecar: " + ex.getMessage());
        }
    }

    void refresh() {
        model.clear();
        files.clear();
        File dl = new File(System.getProperty("user.home"), "Downloads");
        addGlob(dl, "direct-h264", ".mp4");
        addGlob(dl, "asc-rec-", ".wav");
        addGlob(dl, "asc-rec-", ".mp4");
        status.setText(IdcLoop.IDC + "  " + files.size() + " AVD  ·  Index FFT  ·  Search livecode  ·  Loop tesseract");
        if (!files.isEmpty()) list.setSelectedIndex(0);
    }

    void onSelect() {
        File f = selected();
        if (f == null) return;
        Path side = sidecarOf(f);
        if (Files.isRegularFile(side)) loadSidecar(side);
    }

    void pushLoop(String op) {
        plan.setLoop(loopStep);
        elev.setLoop(loopStep);
        modelView.setLoop(loopStep);
        modelView.setOperation(op);
    }

    void loopSel() {
        if (idleClock != null && idleClock.isRunning()) idleClock.stop();
        loopStep = Math.floorMod(loopStep + 1, 16);
        pushLoop(currentSidecar == null ? "IDLE" : "LOOP");
        int[] v = IdcLoop.vertex(loopStep);
        char idc = IdcLoop.IDC.charAt(Math.floorMod(loopStep, 11));
        status.setText(idc + "  sigma " + Sigma9.formula() + "  t_loop " + IdcLoop.bits(v) + "  " + IdcLoop.tetra(v)
                + "  ·  " + (currentSidecar == null ? "inactive surface" : "live")
                + "  ·  frame " + loopStep + "/16");
    }

    void addGlob(File dir, String prefix, String suffix) {
        File[] all = dir.listFiles((d, n) -> n.startsWith(prefix) && n.endsWith(suffix));
        if (all == null) return;
        Arrays.sort(all, Comparator.comparingLong(File::lastModified).reversed());
        int n = 0;
        for (File f : all) {
            files.add(f);
            model.addElement(f.getName());
            if (++n >= 32) break;
        }
    }

    void indexSel() {
        File f = selected();
        if (f == null) { status.setText("select a source"); return; }
        modelView.setOperation("INDEX");
        status.setText("indexing " + f.getName() + " …");
        new SwingWorker<Path, Void>() {
            @Override protected Path doInBackground() {
                runPy("indexer.py", "--file", f.getAbsolutePath());
                return sidecarOf(f);
            }
            @Override protected void done() {
                try {
                    Path side = get();
                    if (Files.isRegularFile(side)) loadSidecar(side);
                    else status.setText("index produced no sidecar");
                } catch (Exception ex) {
                    status.setText("index: " + ex.getMessage());
                }
            }
        }.execute();
    }

    void searchSel() {
        File f = selected();
        Path side = currentSidecar;
        if (side == null && f != null) side = sidecarOf(f);
        if (side == null || !Files.isRegularFile(side)) {
            status.setText("Index first (need .film.json)");
            return;
        }
        String q = FilmLivecode.expand(live.getText());
        live.setText(q);
        modelView.setOperation("SEARCH");
        status.setText(runPy("cli.py", "search", "--q", q, "--file", side.toString()));
        try { loadSidecar(side); } catch (Exception ignored) {}
    }

    void compileSel() {
        Path side = currentSidecar;
        File f = selected();
        if (side == null && f != null) side = sidecarOf(f);
        if (side == null || !Files.isRegularFile(side)) {
            status.setText("Index first");
            return;
        }
        String q = FilmLivecode.expand(live.getText());
        status.setText(runPy("cli.py", "compile", "--prompt", q, "--file", side.toString()));
    }

    void spliceLast() {
        Path edlDir = Path.of(System.getProperty("user.home"),
                ".local/share/gravity-desktop/film-language/edl");
        File last = newest(edlDir.toFile(), ".json");
        if (last == null) { status.setText("no EDL"); return; }
        status.setText(runPy("cli.py", "splice", "--edl", last.getAbsolutePath()));
    }

    void preview() {
        File cuts = new File(System.getProperty("user.home"), "Videos/NLS-Visualist/film-cuts");
        File last = newest(cuts, ".mp4");
        if (last == null) { status.setText("no cut"); return; }
        try {
            new ProcessBuilder("ffplay", "-autoexit", last.getAbsolutePath()).start();
            status.setText("ffplay " + last.getName());
        } catch (Exception ex) {
            status.setText("ffplay: " + ex.getMessage());
        }
    }

    String runPy(String script, String... rest) {
        try {
            List<String> argv = new ArrayList<>();
            argv.add("python3");
            argv.add(py.resolve(script).toString());
            argv.addAll(Arrays.asList(rest));
            ProcessBuilder pb = new ProcessBuilder(argv);
            pb.redirectErrorStream(true);
            pb.environment().put("PYTHONPATH", py.toString());
            Process p = pb.start();
            StringBuilder sb = new StringBuilder();
            try (BufferedReader br = new BufferedReader(
                    new InputStreamReader(p.getInputStream(), StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    if (sb.length() < 600) sb.append(line).append(' ');
                }
            }
            p.waitFor();
            return (p.exitValue() == 0 ? "ok " : "rc=" + p.exitValue() + " ") + sb;
        } catch (Exception ex) {
            return "run: " + ex.getMessage();
        }
    }

    static File newest(File dir, String suffix) {
        if (dir == null || !dir.isDirectory()) return null;
        File[] all = dir.listFiles((d, n) -> n.endsWith(suffix));
        if (all == null || all.length == 0) return null;
        Arrays.sort(all, Comparator.comparingLong(File::lastModified).reversed());
        return all[0];
    }

    public static void main(String[] args) {
        SwingUtilities.invokeLater(() -> {
            GravityDesktopFilm w = new GravityDesktopFilm();
            w.setVisible(true);
        });
    }
}
