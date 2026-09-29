# GravityDesktopLattice — unique subversion

**Does not replace** `GravityDesktop.java` / `./run.sh`.

Connects Gravity recs + downloads to **lattice-dat** (DEMO / LOAD / LIVE / MIX, CRT VIDEO).

```bash
~/Downloads/GravityDesktop/run-lattice-subversion.sh
```

## Right-click

| Menu | Role |
|---|---|
| **Sources locator** | Scan `asc-rec-*.wav`, `direct-h264-*.mp4`, lattice tapes |
| **Operators selector** | DEMO ← video/audio, LOAD, CRT VIDEO, LIVE, MIX, PLAY, REC, DEMOSCENE |

Right-click a **row** to send that file. Right-click **empty** space for operators only.

Main GravityDesktop (WYHIWYREC, catalog) is unchanged.

## Sync with GravityDesktop

`GravityDesktopLattice` watches `REC-SAVED.json`. When GravityDesktop saves a take, the sources list refreshes.

**Sources locator** also scans `/media/$USER`, `/run/media/$USER`, `/mnt`, `~/Videos`, `~/Music`, and extra folders you add (right-click → **Add folder / drive…**). Extra roots persist in `~/.config/gravity-desktop/lattice-source-roots.txt`.

Run both:

```bash
~/Downloads/GravityDesktop/run-both-gravity-lattice.sh
```
