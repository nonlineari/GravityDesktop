import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.net.Socket;
import java.net.SocketTimeoutException;

/**
 * Sigma-9 greeting shared by every Gravity app.
 * Derivatives 1, 2, 3, 3. Sum is 9 and 9 is the maximum.
 * GRAVITY + 0x00 + 0x01 is those 9 bytes.
 */
public final class Sigma9 {
    public static final int[] DERIV = {1, 2, 3, 3};
    public static final int MAX = 9;
    public static final byte[] PROLOGUE = {
        'G', 'R', 'A', 'V', 'I', 'T', 'Y', 0x00, 0x01
    };

    private Sigma9() {}

    public static int sigma() {
        int total = 0;
        for (int d : DERIV) {
            if (d < 1 || d > MAX || total + d > MAX) {
                throw new IllegalStateException("derivative " + d + " breaks sigma max " + MAX);
            }
            total += d;
        }
        if (total != MAX) {
            throw new IllegalStateException("sigma " + total + " != " + MAX);
        }
        return total;
    }

    public static String formula() {
        return "1+2+3+3=9";
    }

    public static boolean prologueOk(byte[] buf) {
        if (buf == null || buf.length != PROLOGUE.length || buf.length != sigma()) return false;
        for (int i = 0; i < PROLOGUE.length; i++) {
            if (buf[i] != PROLOGUE[i]) return false;
        }
        return true;
    }

    private static void readSlice(Socket socket, InputStream raw, byte[] buf, int off, int len, int deriv, int sigmaNow)
            throws IOException {
        int got = 0;
        socket.setSoTimeout(2000);
        while (got < len) {
            int n;
            try {
                n = raw.read(buf, off + got, len - got);
            } catch (SocketTimeoutException stalled) {
                throw new IOException("gravity read stalled, d" + deriv
                    + "/dt empty, sigma=" + sigmaNow + "/9");
            }
            if (n < 0) throw new EOFException("gravity handshake closed");
            if (n == 0) {
                throw new IOException("gravity read derivative 0 at " + deriv + ", sigma=" + sigmaNow);
            }
            got += n;
        }
    }

    /** Fill buf. The first 9 bytes are derivatives 1, 2, 3, 3. A longer field keeps the sum at 9. */
    public static void readFully(Socket socket, InputStream raw, byte[] buf) throws IOException {
        int off = 0;
        int total = 0;
        for (int d : DERIV) {
            if (d < 1 || d > MAX || total + d > MAX) {
                throw new IOException("derivative " + d + " breaks sigma max 9");
            }
            int n = Math.min(d, buf.length - off);
            if (n > 0) {
                readSlice(socket, raw, buf, off, n, d, total);
                off += n;
            }
            total += d;
        }
        if (total != sigma()) {
            throw new IOException("sigma " + total + " != 9");
        }
        if (off < buf.length) {
            readSlice(socket, raw, buf, off, buf.length - off, 0, total);
        }
    }
}
