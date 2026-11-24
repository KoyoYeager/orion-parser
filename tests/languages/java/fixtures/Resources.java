package fixtures;

import java.io.InputStream;
import java.io.IOException;

class Resources {
    private final AutoCloseable saved;
    Resources(AutoCloseable saved) { this.saved = saved; }

    int read(InputStream src) throws Exception {
        try (final var first = src; this.saved; src;) {
            return first.read();
        } catch (final IOException | IllegalStateException ex) {
            throw ex;
        } catch (RuntimeException ex) {
            return -1;
        } finally {
            cleanup();
        }
    }

    void close() throws Exception {
        try { saved.close(); } finally { cleanup(); }
        try { saved.close(); } catch (Exception ex) { cleanup(); }
        try (saved) { cleanup(); }
    }
    void cleanup() {}
}
