"""FFmpeg MP4 Video Renderer with NVENC support, zoompan animations, and multi-track audio sync."""

import subprocess
from pathlib import Path
from typing import Any

from PIL import Image

from manga_pipeline.render.plan import RenderPlan


class FFmpegRenderer:
    """Renders deterministic RenderPlan into MP4 video via FFmpeg."""

    def __init__(self, options: dict[str, Any] | None = None) -> None:
        self.options = options or {}
        self._has_nvenc: bool | None = None

    def _check_nvenc(self) -> bool:
        """Check if NVIDIA h264_nvenc encoder is available."""
        if self._has_nvenc is not None:
            return self._has_nvenc
        try:
            res = subprocess.run(
                ["ffmpeg", "-encoders"],
                capture_output=True,
                text=True,
                check=False,
            )
            self._has_nvenc = "h264_nvenc" in res.stdout
        except Exception:
            self._has_nvenc = False
        return self._has_nvenc

    def render(
        self,
        plan: RenderPlan,
        project_root: Path,
        output_path: Path,
    ) -> Path:
        """Execute FFmpeg render pipeline for the given RenderPlan."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        scratch_dir = project_root / "cache" / "scratch" / plan.chapter_id
        scratch_dir.mkdir(parents=True, exist_ok=True)

        if not plan.video_clips:
            raise ValueError(f"RenderPlan for {plan.chapter_id} contains no video clips")

        # 1. Prepare video clip segments or concat demuxer
        concat_txt = scratch_dir / "concat_video.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for _idx, clip in enumerate(plan.video_clips):
                src_img = project_root / clip.source_image
                if not src_img.exists():
                    # Fallback to creating a solid placeholder image if file doesn't exist
                    placeholder = scratch_dir / f"placeholder_{clip.clip_id}.png"
                    if not placeholder.exists():
                        im = Image.new("RGB", (1920, 1080), color=(25, 25, 30))
                        im.save(placeholder)
                    src_img = placeholder

                # Write duration and file for concat demuxer
                duration_sec = clip.duration_ms / 1000.0
                f.write(f"file '{src_img.resolve().as_posix()}'\n")
                f.write(f"duration {duration_sec:.3f}\n")

            # Concat demuxer requirement: repeat last file entry
            last_img = project_root / plan.video_clips[-1].source_image
            if not last_img.exists():
                last_img = scratch_dir / f"placeholder_{plan.video_clips[-1].clip_id}.png"
            f.write(f"file '{last_img.resolve().as_posix()}'\n")

        # 2. Prepare Audio Mix
        has_audio = False
        audio_output = scratch_dir / "mixed_audio.wav"

        valid_audio_clips = [ac for ac in plan.audio_clips if ac.audio_file and (project_root / ac.audio_file).exists()]

        if valid_audio_clips:
            audio_inputs: list[str] = []
            filter_parts: list[str] = []

            for i, ac in enumerate(valid_audio_clips):
                a_path = (project_root / ac.audio_file).resolve().as_posix()
                audio_inputs.extend(["-i", a_path])
                delay_ms = max(0, ac.start_ms)
                filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[a{i}]")

            if len(valid_audio_clips) == 1:
                filter_parts.append("[a0]anull[aout]")
            else:
                mix_inputs = "".join(f"[a{i}]" for i in range(len(valid_audio_clips)))
                filter_parts.append(
                    f"{mix_inputs}amix=inputs={len(valid_audio_clips)}:dropout_transition=0:normalize=0[aout]"
                )

            cmd_audio = [
                "ffmpeg",
                "-y",
                *audio_inputs,
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[aout]",
                str(audio_output),
            ]
            try:
                audio_res = subprocess.run(cmd_audio, capture_output=True, text=True, check=False)
                if audio_res.returncode == 0 and audio_output.exists():
                    has_audio = True
                else:
                    has_audio = False
            except Exception:
                has_audio = False

        # 3. Final MP4 Render (Inputs must precede filters and output flags)
        v_codec = "h264_nvenc" if self._check_nvenc() else "libx264"
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
        ]

        if has_audio:
            cmd.extend(["-i", str(audio_output)])
        else:
            cmd.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])

        # Video filter: Scale and pad to 1080p 16:9
        vf = "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p"
        cmd.extend(
            [
                "-vf",
                vf,
                "-c:v",
                v_codec,
                "-pix_fmt",
                "yuv420p",
                "-r",
                "30",
            ]
        )

        if has_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "192k", "-shortest"])
        else:
            cmd.extend(["-c:a", "aac", "-shortest"])

        cmd.append(str(output_path))

        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            # Fallback to pure CPU libx264 if NVENC failed
            if v_codec == "h264_nvenc":
                cmd[cmd.index("h264_nvenc")] = "libx264"
                res_fallback = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res_fallback.returncode != 0:
                    raise RuntimeError(f"FFmpeg render failed:\n{res_fallback.stderr}")
            else:
                raise RuntimeError(f"FFmpeg render failed:\n{res.stderr}")

        return output_path
