import logging
import re

from core.tts_preprocess import preprocess_for_tts
import signal
import sys
import threading
import time

from core import config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/tmp/openclaw.log", mode="a"),
    ],
)
log = logging.getLogger("openclaw")
from core.display import Display
from core.record_audio import Recorder, check_audio_level
from models.llm.openclaw_client import stream_response
from core.button_ptt import ButtonPTT, State

if config.AUDIO_PROVIDER == "gemini":
    from models.stt.gemini import transcribe
    from models.tts.gemini import TTSPlayer
elif config.AUDIO_PROVIDER == "glm":
    from models.stt.glm import transcribe
    from models.tts.glm import TTSPlayer
elif config.AUDIO_PROVIDER == "doubao":
    from models.stt.doubao import transcribe
    from models.tts.doubao import TTSPlayer
else:
    from models.stt.openai import transcribe
    from models.tts.openai import TTSPlayer


class Assistant:
    def __init__(self):
        config.print_config()

        self.display = Display(backlight=config.LCD_BACKLIGHT)
        self.recorder = Recorder()
        self.ptt = ButtonPTT(
            self.display.board,
            on_press_cb=self._on_button_press,
            on_release_cb=self._on_button_release,
            on_cancel_cb=self._on_button_cancel,
            cancel_allowed_cb=lambda: (time.monotonic() - self._state_entered_at) >= 2.0,
            on_any_press_cb=self._touch,
            on_abort_listening_cb=self._on_abort_listening,
        )
        self._worker_thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self._dismiss = threading.Event()
        self._worker_gen = 0
        self._response_hold_timeout = 30
        self._sleep_timeout = 60
        self._last_activity = time.monotonic()
        self._last_idle_refresh = 0.0
        self._state_entered_at = 0.0
        self._tts = TTSPlayer() if config.ENABLE_TTS else None

    def _is_stale(self, my_gen: int) -> bool:
        return self._worker_gen != my_gen

    def _touch(self):
        self._last_activity = time.monotonic()
        if self.display.is_sleeping:
            self.display.wake()
            self._go_idle()

    def _on_button_cancel(self):
        """Cancel any active operation (transcribing, thinking, or streaming)."""
        self._touch()
        self._worker_gen += 1
        self._dismiss.set()
        self.display.stop_spinner()
        self.display.stop_character()
        if self._tts:
            self._tts.cancel()
        self._go_idle()
        log.info("button cancel -- back to Ready")

    def _on_abort_listening(self):
        """Called when user presses again while in LISTENING (stuck or abort): stop recorder, go Ready."""
        self.recorder.cancel()
        self.display.stop_character()
        self._go_idle()
        log.info("abort listening -- back to Ready")

    def _on_button_press(self):
        self._touch()
        self._dismiss.set()
        log.info("button pressed -- start recording")
        if self._tts:
            self.display.start_character("listening", self._tts)
        else:
            self.display.set_status(
                "Listening...",
                color=(140, 200, 255),
                subtitle="Speak now",
                accent_color=(60, 140, 255),
            )
        try:
            self.recorder.start()
        except Exception as e:
            log.error("recording start failed: %s", e)
            self._show_error(str(e))

    def _on_button_release(self):
        log.info("button released -- processing")
        t = threading.Thread(target=self._process_utterance, daemon=True)
        t.start()
        self._worker_thread = t

    def _process_utterance(self):
        my_gen = self._worker_gen
        try:
            self._process_utterance_inner(my_gen)
        except Exception as e:
            if not self._is_stale(my_gen):
                log.error("error: %s", e)
                self.display.stop_spinner()
                self.display.stop_character()
                self._show_error(str(e)[:80])
        finally:
            self.display.stop_spinner()
            if not self._is_stale(my_gen) and self.ptt.state in (
                State.TRANSCRIBING, State.THINKING, State.STREAMING,
            ):
                self._go_idle()

    def _process_utterance_inner(self, my_gen: int):
        # --- Stop recording ---
        wav_path = self.recorder.stop()

        # --- Silence gate ---
        rms = check_audio_level(wav_path)
        if rms < config.SILENCE_RMS_THRESHOLD:
            log.info("silence detected (RMS=%.0f), skipping", rms)
            if self._is_stale(my_gen):
                return
            self.display.stop_character()
            self.display.set_status(
                "No speech detected",
                color=(160, 160, 160),
                subtitle="Try again",
                accent_color=(80, 80, 80),
            )
            time.sleep(1.5)
            if not self._is_stale(my_gen):
                self._go_idle()
            return

        if self._is_stale(my_gen):
            return

        # --- Transcribe ---
        self._state_entered_at = time.monotonic()
        self.ptt.state = State.TRANSCRIBING
        if self._tts:
            self.display.set_character_state("thinking")
        else:
            self.display.set_status(
                "Transcribing...",
                color=(255, 230, 100),
                subtitle="One moment",
                accent_color=(255, 180, 0),
            )
        t0 = time.monotonic()
        transcript = transcribe(wav_path)
        log.info("transcribe took %.1fs => %r", time.monotonic() - t0, (transcript[:80] if transcript else "(empty)"))

        if not transcript or self._is_stale(my_gen):
            if not self._is_stale(my_gen):
                log.info("empty transcript, returning to idle")
                self._go_idle()
            return

        # --- Stream response from OpenClaw (with conversation context) ---
        if self._is_stale(my_gen):
            return
        self._state_entered_at = time.monotonic()
        self.ptt.state = State.THINKING
        if not self._tts:
            self.display.start_spinner("Thinking")

        self.ptt.state = State.STREAMING
        first_token = True
        full_response = ""
        tts_buffer = ""
        stream_t0 = time.monotonic()

        for delta in stream_response(transcript):
            if self._is_stale(my_gen) or self._shutdown.is_set():
                break
            if first_token:
                log.info("first token after %.1fs", time.monotonic() - stream_t0)
                if self._tts:
                    self.display.set_character_state("talking")
                self.display.stop_spinner()
                self.display.set_response_text("")
                first_token = False
            full_response += delta
            # Only append text to display if TTS is disabled (character animation owns the screen otherwise)
            if not self._tts:
                self.display.append_response(delta)

            # Streaming TTS: batch 1 sentence at a time for fast response
            if self._tts:
                tts_buffer += delta
                # Match sentence-ending punctuation; skip '.' between digits (e.g. 129.80)
                sentence_ends = list(re.finditer(r"(?<!\d)\.(?!\d)\s*|[!?。！？:：;；]\s*|\n", tts_buffer))
                if len(sentence_ends) >= 1:
                    cut = sentence_ends[0].end()
                    chunk = tts_buffer[:cut].strip()
                    tts_buffer = tts_buffer[cut:]
                    if chunk:
                        self._tts.submit(preprocess_for_tts(chunk))

        # Stale worker: exit without touching display, TTS, or history
        if self._is_stale(my_gen):
            return

        log.info("stream done in %.1fs, %d chars", time.monotonic() - stream_t0, len(full_response))

        # Submit remaining TTS buffer and wait for playback to finish
        if self._tts:
            if tts_buffer.strip():
                self._tts.submit(preprocess_for_tts(tts_buffer.strip()))
            self._tts.flush()
            self.display.stop_character()
            self.display.set_response_text(full_response)
        else:
            self.display.flush_response()

        log.info("response complete -- holding on screen")

        # OpenClaw maintains conversation history server-side via the session key,
        # so we do not need to track and trim history locally anymore.

        self._dismiss.clear()
        self._dismiss.wait(timeout=self._response_hold_timeout)

        # Could have been cancelled during the hold
        if self._is_stale(my_gen):
            return

        if self._dismiss.is_set():
            log.info("dismissed by button press")
        else:
            log.info("display timeout, returning to idle")

        self._go_idle()

    def _go_idle(self):
        self._last_activity = time.monotonic()
        self._last_idle_refresh = time.monotonic()
        self.ptt.state = State.IDLE
        self.display.set_backlight(config.LCD_BACKLIGHT)
        self.display.stop_character()
        self.display.set_idle_screen()

    def _show_error(self, msg: str):
        self.ptt.state = State.ERROR
        self.display.stop_character()
        self.display.set_status(
            msg[:50] + ("..." if len(msg) > 50 else ""),
            color=(255, 120, 120),
            subtitle="Something went wrong",
            accent_color=(200, 0, 0),
        )
        time.sleep(3)
        self._go_idle()

    def run(self):
        self._go_idle()
        log.info("assistant ready -- press button to talk")

        try:
            while not self._shutdown.is_set():
                self._shutdown.wait(timeout=1.0)
                worker_busy = self._worker_thread is not None and self._worker_thread.is_alive()

                # Refresh idle screen periodically (clock update)
                if (
                    not self.display.is_sleeping
                    and self.ptt.state == State.IDLE
                    and not worker_busy
                    and time.monotonic() - self._last_idle_refresh > 30
                ):
                    self.display.set_idle_screen()
                    self._last_idle_refresh = time.monotonic()

                # Sleep display after inactivity
                if (
                    not self.display.is_sleeping
                    and self.ptt.state == State.IDLE
                    and not worker_busy
                    and time.monotonic() - self._last_activity > self._sleep_timeout
                ):
                    log.info("idle timeout -- sleeping display")
                    self.display.sleep()
        except KeyboardInterrupt:
            log.info("shutting down...")
        finally:
            self.shutdown()

    def shutdown(self):
        self._shutdown.set()
        self._worker_gen += 1
        self._dismiss.set()
        self.recorder.cancel()
        if self._tts:
            self._tts.cancel()
        self.display.stop_character()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        self.display.cleanup()
        log.info("cleanup done")


def main():
    assistant = Assistant()

    def _sigterm_handler(signum, frame):
        assistant.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sigterm_handler)
    assistant.run()


if __name__ == "__main__":
    main()
