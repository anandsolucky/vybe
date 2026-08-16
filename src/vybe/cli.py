"""VYBE CLI. Slice 0 command: check — verify the environment is ready."""

import os
import shutil
import sys

from .config import ROOT, load_config, load_env
from .core.avatars import list_avatars, load_avatar


def check() -> int:
    load_env()
    cfg = load_config()
    ok = True

    def row(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and good
        mark = "✓" if good else "✗"
        print(f"  {mark} {label:<28} {detail}")

    print("VYBE environment check")
    row("ffmpeg", shutil.which("ffmpeg") is not None)
    row("config.yaml", bool(cfg), f"delay={cfg.get('delay_seconds')}s")

    for key, needed_for in [
        ("DEEPGRAM_API_KEY", "ASR (Slice 1)"),
        ("ELEVENLABS_API_KEY", "TTS (Slice 3)"),
        ("LLM_API_KEY", "commentary engine (Slice 2)"),
    ]:
        present = bool(os.environ.get(key))
        row(key, present or key == "LLM_API_KEY", needed_for + ("" if present else " — MISSING"))

    lang = cfg.get("default_language", "hi")
    ids = list_avatars(lang)
    row(f"avatars/{lang}", bool(ids), ", ".join(ids))
    for avatar_id in ids:
        avatar = load_avatar(lang, avatar_id)
        detail = f"{avatar.engine} voice={avatar.voice_id} rate={avatar.speaking_rate_wps}w/s ({avatar.status})"
        row(f"  {avatar.name}", bool(avatar.voice_id), detail)

    row("poc/source.mov", (ROOT / "poc" / "source.mov").exists(), "dev harness input")
    print("ready" if ok else "issues found (LLM key may wait until Slice 2)")
    return 0 if ok else 1


def live(args: list[str]) -> int:
    load_env()
    cfg = load_config()
    input_spec = args[0] if args else str(ROOT / "poc" / "source.mov")
    video = "--video" in args
    from .core.live import run
    run(input_spec, cfg.get("delay_seconds", 15), video=video)
    return 0


def direct(args: list[str]) -> int:
    """Golden test: media file -> transcript -> director -> segments."""
    import json as jsonlib
    import subprocess
    import tempfile

    load_env()
    cfg = load_config()
    input_path = args[0] if args else str(ROOT / "poc" / "source.mov")
    lang = cfg.get("default_language", "hi")
    avatar_id = args[1] if len(args) > 1 else cfg.get("default_avatar", "kabir")

    from .core.avatars import load_avatar
    from .core.director import Director, spoken_words
    from .providers.asr_deepgram import DeepgramASR
    from .providers.llm_openai import OpenAICompatibleLLM

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", input_path,
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", tmp.name],
            check=True,
        )
        words = DeepgramASR().transcribe_file(tmp.name)
    print(f"transcript: {len(words)} words")

    avatar = load_avatar(lang, avatar_id)
    director = Director(OpenAICompatibleLLM(), avatar)
    segments = director.direct(words)

    rate = avatar.speaking_rate_wps
    all_fit = True
    print(f"\n{avatar.name} segments:")
    for s in segments:
        n = spoken_words(s.text)
        est = n / rate
        fit = "OK " if est <= s.slot else "LONG"
        all_fit = all_fit and est <= s.slot
        print(f"  [{s.anchor:6.2f}s slot {s.slot:4.1f}s] {n:2d}w ~{est:4.1f}s {fit} {s.text}")

    out = ROOT / "poc" / "segments.json"
    out.write_text(jsonlib.dumps(
        [{"text": s.text, "anchor": s.anchor, "slot_end": s.slot_end} for s in segments],
        ensure_ascii=False, indent=2,
    ))
    print(f"\nsaved {len(segments)} segments -> {out}")
    print("fit estimate:", "all OK" if all_fit else "some LONG — tighten budgets")
    return 0 if all_fit else 1


def render(args: list[str]) -> int:
    """Full offline pipeline: media -> segments (saved or fresh) -> video."""
    import json as jsonlib

    load_env()
    cfg = load_config()
    input_path = args[0] if args else str(ROOT / "poc" / "source.mov")
    avatar_id = args[1] if len(args) > 1 and not args[1].startswith("--") \
        else cfg.get("default_avatar", "kabir")

    from .core.avatars import load_avatar
    from .core.pipeline import render_file
    from .providers.base import DeliverySegment

    segments_path = None
    for i, arg in enumerate(args):
        if arg == "--segments" and i + 1 < len(args):
            segments_path = args[i + 1]

    if segments_path:
        data = jsonlib.loads((ROOT / segments_path).read_text())
        segments = [DeliverySegment(d["text"], d["anchor"], d["slot_end"]) for d in data]
        print(f"loaded {len(segments)} segments from {segments_path}")
    else:
        print("no --segments given: running transcript + director first")
        code = direct([input_path, avatar_id])
        if code != 0:
            return code
        data = jsonlib.loads((ROOT / "poc" / "segments.json").read_text())
        segments = [DeliverySegment(d["text"], d["anchor"], d["slot_end"]) for d in data]

    avatar = load_avatar(cfg.get("default_language", "hi"), avatar_id)
    out_path = str(ROOT / "poc" / f"vybe_{avatar_id}_auto.mp4")
    report = render_file(input_path, avatar, cfg, segments, out_path)

    print(f"\n{'anchor':>7} {'slot':>6} {'audio':>6} {'speed':>5}  fit")
    all_fit = True
    for r in report:
        all_fit = all_fit and r["fits"]
        print(f"{r['anchor']:>6.2f}s {r['slot']:>5.2f}s {r['audio']:>5.2f}s "
              f"{r['speed']:>5.2f}  {'OK' if r['fits'] else 'OVERFLOW'}")
    print(f"\noutput: {out_path}")
    return 0 if all_fit else 1


def play(args: list[str]) -> int:
    """Slice 4: run the live pipeline + player server."""
    import json as jsonlib
    import tempfile
    import time as timelib
    from pathlib import Path

    load_env()
    cfg = load_config()
    input_path = args[0] if args and not args[0].startswith("--") \
        else str(ROOT / "poc" / "source.mov")
    avatar_id = cfg.get("default_avatar", "kabir")
    port = 8791
    replay = None
    if "--tab" in args:
        input_path = "browser"
    elif "--screen" in args:
        from .core.capture import list_devices
        devices = list_devices()
        video_idx = next((i for i, n in devices["video"] if "Capture screen 0" in n), None)
        audio_idx = next((i for i, n in devices["audio"] if "BlackHole" in n), None)
        if video_idx is None or audio_idx is None:
            print("need a screen device and BlackHole audio; run: vybe devices")
            return 1
        input_path = f"screen:{video_idx}:{audio_idx}"
        print(f"screen capture: video={video_idx} audio={audio_idx} (BlackHole)")
    for i, arg in enumerate(args):
        if arg == "--replay" and i + 1 < len(args):
            from .providers.base import DeliverySegment
            data = jsonlib.loads((ROOT / args[i + 1]).read_text())
            replay = [DeliverySegment(d["text"], d["anchor"], d["slot_end"]) for d in data]
        if arg == "--port" and i + 1 < len(args):
            port = int(args[i + 1])

    from .core.avatars import load_avatar
    from .core.live_pipeline import LiveSession
    from . import server as srv

    avatar = load_avatar(cfg.get("default_language", "hi"), avatar_id)
    session_dir = Path(tempfile.mkdtemp(prefix="vybe_session_"))

    ingest = None
    if input_path == "browser":
        from .ingest import TabIngest
        ingest = TabIngest(8790)
        ingest.start()

    session = LiveSession(input_path, avatar, None, cfg, session_dir,
                          replay=replay, ingest=ingest)
    srv.start(session, input_path, session_dir, port)
    mode = "replay" if replay else ("tab" if ingest else "live")
    print(f"VYBE player: http://127.0.0.1:{port}  (mode: {mode}, avatar {avatar.name})")
    if ingest:
        print("open the player, press CAPTURE TAB, pick the tab playing the "
              "match, tick 'Also share tab audio'")

    llm = None
    if replay is None:
        from .providers.llm_openai import OpenAICompatibleLLM
        llm = OpenAICompatibleLLM()

    import threading
    pipeline = threading.Thread(target=session.run, args=(llm,), daemon=True)
    pipeline.start()
    try:
        while True:
            timelib.sleep(1)
    except KeyboardInterrupt:
        return 0


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "check"
    if command == "check":
        sys.exit(check())
    if command == "live":
        sys.exit(live(sys.argv[2:]))
    if command == "direct":
        sys.exit(direct(sys.argv[2:]))
    if command == "render":
        sys.exit(render(sys.argv[2:]))
    if command == "play":
        sys.exit(play(sys.argv[2:]))
    if command == "devices":
        load_env()
        from .core.capture import list_devices
        devices = list_devices()
        for kind in ("video", "audio"):
            print(f"{kind}:")
            for idx, name in devices[kind]:
                print(f"  [{idx}] {name}")
        sys.exit(0)
    print(f"unknown command: {command} "
          f"(available: check, live, direct, render, play, devices)")
    sys.exit(2)


if __name__ == "__main__":
    main()
