import javax.swing.JComponent;
import java.awt.Color;
import java.awt.Dimension;
import java.awt.Graphics;
import java.awt.Graphics2D;

/** ELEVATION — AUDIO IN α vs AUDIO OUT β + DualLattice residual ε. */
final class ElevationPanel extends JComponent {
    static final Color ACCENT = new Color(0x5ad0c8);
    static final Color GOLD = new Color(0xe6b84d);
    static final Color MUTED = new Color(0x8b95a5);

    private FilmDoc doc;
    private int loopStep;

    ElevationPanel() {
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
        g2.setColor(getBackground());
        g2.fillRect(0, 0, getWidth(), getHeight());
        boolean idle = doc == null || doc.fftIn.length < 2;
        float[] inn = idle ? IdleSurface.fft(loopStep, 0, false) : doc.fftIn;
        float[] out = idle ? IdleSurface.fft(loopStep, 0, true)
                : (doc.fftOut.length > 0 ? doc.fftOut : doc.fftIn);
        int mid = getHeight() / 2;
        g2.setColor(MUTED);
        g2.drawString(idle ? "AUDIO IN  α  ·  inactive" : "AUDIO IN  α", 8, 14);
        bars(g2, inn, 16, mid - 24, ACCENT, getWidth());
        g2.setColor(MUTED);
        g2.drawString(idle ? "AUDIO OUT  β  ·  inactive" : "AUDIO OUT  β", 8, mid + 14);
        bars(g2, out, mid + 16, mid - 24, GOLD, getWidth());
        double eps = idle ? IdleSurface.epsilon(loopStep) : doc.epsilonSec;
        g2.setColor(ACCENT);
        g2.drawString(String.format("ε %.3f ms   DualLattice%s",
                eps * 1000.0, idle ? "  ·  generated" : ""), 8, getHeight() - 8);
    }

    static void bars(Graphics2D g2, float[] mag, int y0, int h, Color c, int w) {
        if (mag == null || mag.length == 0 || h <= 0) return;
        float bw = Math.max(1f, (w - 16f) / mag.length - 1f);
        g2.setColor(c);
        for (int i = 0; i < mag.length; i++) {
            float v = Math.max(0f, Math.min(1f, mag[i]));
            int bh = (int) (v * (h - 8));
            g2.fillRect((int) (8 + i * (bw + 1)), y0 + h - 4 - bh, Math.max(1, (int) bw), bh);
        }
    }
}
