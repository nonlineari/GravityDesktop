#!/usr/bin/env python3
"""Pipeline convert + gravity-server embed tests.

Reproduces ffmpeg 6.1 failing on unlabeled 6-channel AAC
(jobs 37/38: 'Unsupported channel layout "6 channels"', exit 234).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import nls_video_pipe as nvp


def _ffmpeg_available() -> bool:
    return bool(nvp.shutil.which("ffmpeg"))


def _make_six_channel_mp4(path: Path, duration: float = 0.4) -> Path:
    """Tiny MP4 with unlabeled 6-channel AAC — ffmpeg 6.1 AAC encoder rejects this."""
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size=320x180:rate=10:duration={duration}",
        "-f", "lavfi", "-i", (
            f"anullsrc=channel_layout=hexagonal:sample_rate=48000:duration={duration}"
        ),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(path),
    ]
    subprocess.check_call(cmd)
    return path


class NlsCodecTests(unittest.TestCase):
    """NLS Codec (nls) — short name nonlineari. Keep stereo, quad, 5.1, 6ch, 7.1/8ch."""

    def test_name_is_nls_codec_alias_nonlineari(self):
        self.assertEqual(nvp.NLS_CODEC_NAME, "nls")
        self.assertEqual(nvp.NLS_CODEC_LABEL, "NLS Codec")
        self.assertEqual(nvp.NLS_CODEC_ALIAS, "nonlineari")

    def test_stereo_plan(self):
        plan = nvp.nls_codec_plan(2, "stereo")
        self.assertEqual(plan["name"], "nls")
        self.assertEqual(plan["alias"], "nonlineari")
        self.assertEqual(plan["layout"], "stereo")
        self.assertEqual(plan["channels"], 2)
        self.assertNotIn("-ac", plan["ffmpeg"])
        self.assertIn("192k", plan["ffmpeg"])

    def test_quad_plan(self):
        plan = nvp.nls_codec_plan(4, None)
        self.assertEqual(plan["layout"], "quad")
        self.assertEqual(plan["channels"], 4)
        joined = " ".join(plan["ffmpeg"])
        self.assertIn("pan=quad", joined)
        self.assertNotIn("-ac 2", joined)

    def test_sixch_plan_is_5_1_not_stereo(self):
        plan = nvp.nls_codec_plan(6, None)
        self.assertEqual(plan["layout"], "5.1")
        self.assertEqual(plan["channels"], 6)
        joined = " ".join(plan["ffmpeg"])
        self.assertIn("pan=5.1", joined)
        self.assertNotIn("-ac", plan["ffmpeg"])
        self.assertIn("448k", plan["ffmpeg"])

    def test_eightch_plan_is_7_1(self):
        plan = nvp.nls_codec_plan(8, None)
        self.assertEqual(plan["layout"], "7.1")
        self.assertEqual(plan["channels"], 8)
        self.assertIn("pan=7.1", " ".join(plan["ffmpeg"]))
        self.assertIn("640k", plan["ffmpeg"])

    def test_build_cmd_sixch_keeps_surround(self):
        cmd = nvp.build_convert_cmd(
            Path("/tmp/in.mp4"),
            Path("/tmp/out.partial.mp4"),
            nvp.DEFAULT_PRESETS["balanced-4k"],
            audio_channels=6,
        )
        joined = " ".join(cmd)
        self.assertNotIn("-ac 2", joined)
        self.assertIn("pan=5.1", joined)
        self.assertIn("NLS Codec", joined)

    def test_video_only_skips_audio_encoder(self):
        cmd = nvp.build_convert_cmd(
            Path("/tmp/in.mp4"),
            Path("/tmp/out.partial.mp4"),
            nvp.DEFAULT_PRESETS["fast-1080"],
            audio_channels=0,
        )
        self.assertNotIn("-c:a", cmd)
        self.assertNotIn("-ac", cmd)

    def _convert_and_probe(self, src: Path, channels: int, layout: Optional[str]):
        partial = src.parent / "out.partial.mp4"
        cmd = nvp.build_convert_cmd(
            src, partial, nvp.DEFAULT_PRESETS["fast-1080"],
            audio_channels=channels,
            audio_layout=layout,
        )
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(
            proc.returncode, 0,
            f"ffmpeg failed rc={proc.returncode}\nstderr={(proc.stderr or '')[-1500:]}",
        )
        info = nvp.probe_audio_info(partial)
        playable = nvp._verify_media_playable(partial, sample_sec=0.3)
        self.assertTrue(playable.get("ok"), playable)
        return info

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg not on PATH")
    def test_six_channel_source_stays_5_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _make_six_channel_mp4(Path(tmp) / "sixch.mp4")
            info = nvp.probe_audio_info(src)
            out = self._convert_and_probe(src, info.get("channels"), info.get("channel_layout"))
            self.assertEqual(int(out.get("channels") or 0), 6)
            self.assertEqual(out.get("channel_layout"), "5.1")

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg not on PATH")
    def test_stereo_and_quad_convert(self):
        with tempfile.TemporaryDirectory() as tmp:
            stereo = Path(tmp) / "st.mp4"
            subprocess.check_call([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=0.3",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000:duration=0.3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(stereo),
            ])
            st = self._convert_and_probe(stereo, 2, "stereo")
            self.assertEqual(int(st.get("channels") or 0), 2)

            quad = Path(tmp) / "q.mp4"
            subprocess.check_call([
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=0.3",
                "-f", "lavfi", "-i", "anullsrc=channel_layout=quad:sample_rate=48000:duration=0.3",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", str(quad),
            ])
            q = self._convert_and_probe(quad, 4, "quad")
            self.assertEqual(int(q.get("channels") or 0), 4)
            self.assertEqual(q.get("channel_layout"), "quad")


class GravityChannelTests(unittest.TestCase):
    """Gravity split/mix: discrete analog packets, mix back to NLS Codec layout."""

    def test_labels_follow_layout(self):
        self.assertEqual(nvp.gravity_channel_labels(2), ("FL", "FR"))
        self.assertEqual(nvp.gravity_channel_labels(4), ("FL", "FR", "BL", "BR"))
        self.assertEqual(nvp.gravity_channel_labels(6), ("FL", "FR", "FC", "LFE", "BL", "BR"))
        self.assertEqual(nvp.gravity_channel_labels(8)[-2:], ("SL", "SR"))

    @unittest.skipUnless(_ffmpeg_available(), "ffmpeg not on PATH")
    def test_split_and_mix_sixch(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _make_six_channel_mp4(Path(tmp) / "six.mp4")
            result = nvp.prepare_audio_gravity_channels(src, Path(tmp) / "g")
            self.assertTrue(result.get("ok"), result)
            self.assertEqual(result.get("layout"), "5.1")
            self.assertEqual(int(result.get("channels") or 0), 6)
            split = result.get("split") or []
            self.assertEqual(len(split), 6)
            for p in split:
                self.assertTrue(Path(p).is_file() and Path(p).stat().st_size > 200)
            mix = Path(result["mix"])
            self.assertTrue(mix.is_file())
            info = nvp.probe_audio_info(mix)
            self.assertEqual(int(info.get("channels") or 0), 6)
            self.assertEqual(info.get("channel_layout"), "5.1")


class GravityServerEmbedTests(unittest.TestCase):
    def test_start_gravity_server_thread_handshakes(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        started = nvp.start_gravity_server_thread(host="127.0.0.1", port=port)
        self.assertTrue(started.get("ok"))
        deadline = time.time() + 3.0
        last_err = None
        while time.time() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=0.4)
                s.settimeout(1.0)
                import sigma9
                self.assertEqual(sigma9.sigma(), 9)
                prologue = sigma9.read_sigma9(s, 9)
                sigma9.check_prologue(prologue)
                self.assertEqual(len(prologue), 9)
                s.sendall(b"\x42" * 32)
                hello = sigma9.read_sigma9(s, 32)
                self.assertEqual(len(hello), 32)
                s.sendall(b"\x43" * 48)
                line = b""
                while b"\n" not in line:
                    chunk = s.recv(4096)
                    if not chunk:
                        break
                    line += chunk
                s.close()
                self.assertIn(b"gravity_update", line)
                return
            except OSError as e:
                last_err = e
                time.sleep(0.05)
        self.fail(f"gravity-server did not handshake on :{port}: {last_err}")


def _fmt_table(*rows: str) -> list:
    return [
        "[info] Available formats for TESTID:",
        "ID  EXT   RESOLUTION FPS | FILESIZE   TBR PROTO | VCODEC MORE INFO",
        "-----------------------------------------------------------------",
        *rows,
    ]


def _youtube_dash() -> list:
    return _fmt_table(
        "sb0 mhtml 320x180      1    |                mhtml | images                    storyboard",
        "18  mp4   640x360     24  2 |  21.31MiB  730k https | avc1.42001E mp4a.40.2 44k 360p",
        "134 mp4   640x360     24    |  16.34MiB  560k https | avc1.4d401e     560k video only",
        "137 mp4   1920x1080   24    | 113.97MiB 3906k https | avc1.640028    3906k video only",
        "270 mp4   1920x1080   24    | ~137.31MiB 4701k m3u8  | avc1.640028    4701k video only",
        "248 webm  1920x1080   24    |  76.83MiB 2633k https | vp9            2633k video only",
        "313 webm  3840x2160   24    | 491.18MiB 16835k https | vp9           16835k video only",
        "401 mp4   3840x2160   24    | 316.03MiB 10832k https | av01.0.12M.08 10832k video only",
        "625 mp4   3840x2160   24    | ~569.44MiB 19497k m3u8  | vp09.00.50.08 19497k video only",
        "140 m4a   audio only      2 |   3.00MiB  129k https | audio only          mp4a.40.2  129k 44k",
    )


class GravityServeFormatTests(unittest.TestCase):
    def test_youtube_clients_expose_dash(self):
        args = nvp.youtube_player_client_args()
        self.assertIn("tv_embedded", args)
        self.assertIn("android_sdkless", args)
        self.assertFalse(args.startswith("youtube:player_client=web"))

    def test_select_360_1080_2160(self):
        rows = _youtube_dash()
        self.assertEqual(nvp.select_format_from_list(rows, False, False, 360), "18")
        self.assertEqual(nvp.select_format_from_list(rows, False, False, 1080), "137+140")
        self.assertEqual(nvp.select_format_from_list(rows, False, False, 2160), "313+140")

    def test_2160_falls_back_to_1080_not_360(self):
        rows = _fmt_table(
            "18  mp4   640x360     24  2 |  21.31MiB  730k https | avc1.42001E mp4a.40.2 44k 360p",
            "137 mp4   1920x1080   24    | 113.97MiB 3906k https | avc1.640028    3906k video only",
            "140 m4a   audio only      2 |   3.00MiB  129k https | audio only          mp4a.40.2",
        )
        self.assertEqual(nvp.select_format_from_list(rows, False, False, 2160), "137+140")

    def test_ytdlp_format_for_height(self):
        self.assertIn("height=2160", nvp.ytdlp_format_for_height(2160))
        self.assertIn("height=1080", nvp.ytdlp_format_for_height(1080))
        self.assertIn("height<=360", nvp.ytdlp_format_for_height(360))

    def test_preset_target_height(self):
        self.assertEqual(nvp.preset_target_height("fast-1080"), 1080)
        self.assertEqual(nvp.preset_target_height("balanced-4k"), 2160)
        self.assertEqual(nvp.preset_target_height("hq-4k"), 2160)

    def test_vp9_to_h264_args_keep_pixels(self):
        args = nvp.vp9_to_h264_args("/in.mp4", "/out-avc.mp4")
        joined = " ".join(args)
        self.assertIn("libx264", args)
        self.assertIn("19", args)
        self.assertNotIn("-vf", args)
        self.assertNotIn("scale=", joined)

    def test_balanced_4k_convert_does_not_scale(self):
        cmd = nvp.build_convert_cmd(
            Path("/tmp/in.mp4"),
            Path("/tmp/out.partial.mp4"),
            nvp.DEFAULT_PRESETS["balanced-4k"],
            audio_channels=2,
        )
        joined = " ".join(cmd)
        self.assertIn("libx264", cmd)
        self.assertNotIn("scale=", joined)

    def test_transcode_needed(self):
        self.assertTrue(nvp.is_transcode_needed("vp9"))
        self.assertTrue(nvp.is_transcode_needed("av01.0.12M.08"))
        self.assertFalse(nvp.is_transcode_needed("h264"))
        self.assertFalse(nvp.is_transcode_needed("avc1"))

    def test_h264_sibling_path(self):
        self.assertEqual(
            nvp.h264_sibling_path("/tmp/direct-h264-example-003.mp4"),
            "/tmp/direct-h264-example-003-avc.mp4",
        )


if __name__ == "__main__":
    unittest.main()

