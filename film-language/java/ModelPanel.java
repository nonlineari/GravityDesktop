import javax.swing.JComponent;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Font;
import java.awt.Graphics;
import java.awt.Graphics2D;
import java.awt.RenderingHints;

/** MODEL — ObserverStage composed with ⿲…⿰ (11D stair). Escher wrap, Duchamp frames. */
final class ModelPanel extends JComponent {
    static final double PHI = 1.6180339887;
    static final Color ACCENT = new Color(0x5ad0c8);
    static final Color GOLD = new Color(0xe6b84d);
    static final Color INK = new Color(0xe8ecf1);
    static final Color MAGENTA = new Color(0xff3dce);
    static final Color MUTED = new Color(0x8b95a5);

    private FilmDoc doc;
    private int loopStep;
    private String operation = "IDLE";

    ModelPanel() {
        setOpaque(true);
        setBackground(new Color(0x111214));
        setPreferredSize(new Dimension(320, 220));
        setFont(new Font("SansSerif", Font.PLAIN, 12));
    }

    void setDoc(FilmDoc d) { doc = d; repaint(); }

    void setLoop(int step) { loopStep = step; repaint(); }

    void setOperation(String op) {
        operation = op == null || op.isEmpty() ? "IDLE" : op;
        repaint();
    }

    @Override
    protected void paintComponent(Graphics g) {
        Graphics2D g2 = (Graphics2D) g;
        g2.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
        g2.setColor(getBackground());
        g2.fillRect(0, 0, getWidth(), getHeight());
        int w = getWidth(), h = getHeight();
        int ox = (int) (w * 0.28), oy = (int) (h * 0.72);
        g2.setColor(ACCENT);
        g2.drawLine(20, oy, w - 20, oy);
        g2.drawString("N", w - 28, oy - 6);
        g2.drawString("N", 8, oy - 6);
        g2.drawString("Z", ox - 8, 16);

        // 11 IDC rays — hierarchy 11→1 around the observer (Man Ray stills)
        int n = 11;
        g2.setFont(getFont());
        for (int i = 0; i < n; i++) {
            double ang = Math.PI * 0.12 + i * (Math.PI * 0.70 / Math.max(1, n - 1));
            double r = 36 + (i + 1) * 11 * PHI / 3;
            int x = ox + (int) (r * Math.cos(ang));
            int y = oy - (int) (r * Math.sin(ang));
            boolean here = i == Math.floorMod(loopStep, n);
            g2.setColor(here ? MAGENTA : GOLD);
            g2.drawLine(ox, oy, x, y);
            g2.setColor(here ? MAGENTA : INK);
            g2.drawString(String.valueOf(IdcLoop.IDC.charAt(i)), x - 6, y + 5);
        }

        // Gray-code tesseract walk (Escher) — 16 finite steps
        int[] v = IdcLoop.vertex(loopStep);
        g2.setColor(ACCENT);
        g2.fillOval(ox - 5, oy - 5, 10, 10);
        g2.setColor(MUTED);
        g2.drawString(IdcLoop.IDC, 8, 16);
        boolean idle = doc == null || doc.fftIn.length < 2;
        g2.setColor(idle ? MAGENTA : MUTED);
        g2.drawString("OP " + operation + "  t_loop " + IdcLoop.bits(v) + "  " + IdcLoop.tetra(v), 8, h - 10);
        int shots = doc == null ? 0 : doc.shots;
        g2.setColor(MUTED);
        if (shots > 0) g2.drawString(shots + " stills", w - 72, 16);
        else g2.drawString(idle ? "inactive" : "live", w - 64, 16);
    }
}
