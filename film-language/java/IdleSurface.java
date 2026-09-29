/** Inactive display generated inside PLAN / ELEVATION / MODEL.
 * Runs without a sidecar: φ-harmonics of the Gray tesseract walk.
 */
final class IdleSurface {
    static final int BINS = 64;
    static final double PHI = 1.6180339887;

    static float[] fft(int step, int track, boolean out) {
        float[] mag = new float[BINS];
        int[] v = IdcLoop.vertex(step);
        double phase = step * 0.22 + track * 0.41;
        if (out) phase += PHI;
        for (int i = 0; i < BINS; i++) {
            double t = i / (double) (BINS - 1);
            double s = 0;
            for (int d = 0; d < 4; d++) {
                double w = v[d] == 1 ? (d + 1) : 0.25 * (d + 1);
                s += Math.sin(2 * Math.PI * w * t * PHI + phase * (d + 1) * 0.15);
            }
            mag[i] = (float) (0.12 + 0.88 * Math.abs(s) / 4.0);
        }
        return mag;
    }

    static double[] ticks() {
        double[] t = new double[16];
        for (int i = 0; i < 16; i++) t[i] = i / 15.0;
        return t;
    }

    static double epsilon(int step) {
        int[] v = IdcLoop.vertex(step);
        return (v[3] * 0.0203) + (Math.floorMod(step, 16) * 0.0004);
    }

    static String op(boolean indexed, int step) {
        if (!indexed) return "IDLE  " + IdcLoop.mark(11 - Math.floorMod(step, 11));
        return "LIVE  " + IdcLoop.mark(11 - Math.floorMod(step, 11));
    }
}
