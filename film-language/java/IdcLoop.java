/** ⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿰ — 11 composition ops on the 11D stair.
 * Tetragrammaton YHWH → tesseract x,y,z,t. Gray walk = Escher wrap (finite 16 / infinite).
 * Duchamp: one bit-flip per frame. Man Ray: vertex = still.
 */
final class IdcLoop {
    static final String IDC = "⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻⿰";
    static final String[] TETRA = {"Y", "H", "W", "H"};
    static final String[] DIMS = {"x", "y", "z", "t"};

    static char mark(int level11to1) {
        int i = 11 - level11to1;
        if (i < 0) i = 0;
        if (i > 10) i = 10;
        return IDC.charAt(i);
    }

    static int[][] gray4() {
        int[][] w = new int[16][4];
        for (int i = 0; i < 16; i++) {
            int g = i ^ (i >> 1);
            for (int d = 0; d < 4; d++) w[i][d] = (g >> d) & 1;
        }
        return w;
    }

    static int[] vertex(int step) {
        int[][] w = gray4();
        return w[Math.floorMod(step, 16)];
    }

    static String bits(int[] v) {
        return "" + v[0] + v[1] + v[2] + v[3];
    }

    static String tetra(int[] v) {
        return TETRA[0] + v[0] + TETRA[1] + v[1] + TETRA[2] + v[2] + TETRA[3] + v[3];
    }

    public static void main(String[] args) {
        int[][] w = gray4();
        if (w.length != 16) System.exit(1);
        int[] last = w[15], first = w[0];
        int flips = 0;
        for (int d = 0; d < 4; d++) if (last[d] != first[d]) flips++;
        if (flips != 1) System.exit(2);
        if (Sigma9.sigma() != 9 || Sigma9.PROLOGUE.length != 9) System.exit(3);
        System.out.println(IDC + "  wrap " + bits(last) + "→" + bits(first) + "  sigma " + Sigma9.formula());
    }
}
