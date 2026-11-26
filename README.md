# hianime-cli

Terminal client for searching, browsing, watching, and downloading anime from hianime.ms.

## Requirements

- Python 3.10+
- `mpv` for playback
- `ffmpeg` for downloads
- `cryptography` for supported stream decryption

Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

## Run

```bash
./hianime-cli
./hianime-cli search "one piece"
./hianime-cli info "one piece"
./hianime-cli watch 12 --url https://hianime.ms/details/one-piece-1a877
./hianime-cli download 12 --url https://hianime.ms/details/one-piece-1a877
./hianime-cli continue
```

With no command, the app opens a full-screen browser when run in a terminal.
Use the arrow keys to browse, Enter to open a title or play an episode, `l` to
switch between sub and dub, `v` to switch stream servers, and `d` to download
the selected episode. Press `q` to go back. Search, charts, A-Z, genres,
airing schedule, random picks, history, and settings are available from the
main menu. The text-command shell remains available when stdin is not a TTY.
Settings and watch history are saved between runs. The player checkpoints
playback position every few seconds, so Continue Watching resumes close to
where playback stopped. When an episode has a saved position, the browser
offers resume or start-over. Intro/outro skipping only triggers when playback
crosses a valid timing marker, and ignores markers that would seek to the end
of the media. Multiple intro/outro markers are supported when the stream
provides them; Black Clover also has a known 0:00–0:37 intro segment before its
stream-provided intro marker. Filler skipping applies to next/previous navigation and
autoplay, while filler episodes remain selectable manually.

Downloads are saved under `~/Videos/hianime` by default.

## Configuration

Settings live at `$XDG_CONFIG_HOME/hianime-cli/settings.json` and state at `$XDG_STATE_HOME/hianime-cli/state.json`.

```bash
./hianime-cli config
./hianime-cli config lang dub
./hianime-cli config server vidnest
./hianime-cli config autoplay_next false
./hianime-cli config skip_intro true
./hianime-cli config skip_outro true
./hianime-cli config skip_filler true
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```
