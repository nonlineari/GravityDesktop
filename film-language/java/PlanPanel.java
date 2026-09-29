import javax.swing.JComponent;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.RenderingHints;

/** PLAN — 6-track FFT timeline (Form Follows Timeline). */
final class PlanPanel extends JComponent {
    static final Color MAGENTA = new Color(0xff3dce);
    static final Color ACCENT = new Color(0x5ad0c8);
    static final Color GOLD = new Color(0xe6b84d);
    static final Color MUTED = new Color(0x8b95a5);

    private FilmDoc doc;
    private int loopStep;

    PlanPanel() {
        setOpaque(true);
        setBackground(new Color(0x0a0c10));
        setPreferredSize(new Dimension(320, 220));
        setFont(new java.awt.Font("SansSerif", java.awt.Font.PLAIN, 11));
    }

    void setDoc(FilmDoc d) { doc = d; repaint(); }

    void setLoop(int step) { loopStep = step; repaint(); }

    @Override
    protected void paintComponent(Graphics g) {
        Graphics2D g2 = (Graphics2D) g;
        g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g2.setColor(getBackground());
        g2.fillRect(0, 0, getWidth(), getHeight());
        String[] roles = doc == null || doc.roles.length == 0
                ? new String[]{"WNIM", "FLHS", "ILL(T)", "ILY(R)", "SLEG(L)", "LOGOS(Q)"}
                : doc.roles;
        int n = Math.min(6, Math.max(1, roles.length));
        boolean idle = doc == null || doc.fftIn.length < 2;
        double[] verts = idle ? IdleSurface.ticks() : doc.vertT;
        double T = idle || doc.duration <= 0 ? 1.0 : doc.duration;
        int w = getWidth();
        int h = getHeight() / n;
        for (int i = 0; i < n; i++) {
            int y = i * h;
            g2.setColor(MAGENTA);
            g2.drawRect(0, y, w - 1, Math.max(1, h - 2));
            g2.setColor(MUTED);
            String lab = (i < roles.length ? roles[i] : ("T" + i));
            if (i < IdcLoop.IDC.length()) lab = IdcLoop.IDC.charAt(i) + " " + lab;
            g2.drawString(lab, 6, y + 14);
            float[] fft = idle ? IdleSurface.fft(loopStep, i, false) : doc.fftIn;
            g2.setColor(idle ? new Color(90, 208, 200, 180) : ACCENT);
            int prevx = 60, prevy = y + h - 4;
            for (int x = 0; x < fft.length; x++) {
                int px = 60 + (int) (x / (float) Math.max(1, fft.length - 1) * (w - 70));
                int py = y + h - 4 - (int) (fft[x] * (h - 16));
                g2.drawLine(prevx, prevy, px, py);
                prevx = px;
                prevy = py;
            }
        }
        g2.setColor(GOLD);
        for (int vi = 0; vi < verts.length; vi++) {
            int x = 60 + (int) ((verts[vi] / T) * (w - 70));
            g2.drawLine(x, 2, x, getHeight() - 2);
        }
        // Escher wrap cursor — Gray step as a Duchamp frame on the timeline
        g2.setColor(MAGENTA);
        int cx = 60 + (int) ((Math.floorMod(loopStep, 16) / 15.0) * (w - 70));
        g2.fillRect(cx - 1, 0, 3, getHeight());
    }
}
