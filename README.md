# termcast

**High-resolution terminal session recordings from a YAML script.**

Instead of screen-recording your terminal (blurry, 72 dpi, tied to your monitor resolution), termcast renders each frame as styled HTML in a headless browser, screenshots at 2× pixel density, then encodes the frames into video with FFmpeg. The result is a crisp 2560×1440 or 3840×2160 MP4, GIF, or WebM — indistinguishable from a real terminal but razor-sharp at any zoom level.

```
┌─────────────────────────────────────────────────────────────────┐
│  demo.yaml  →  Scene Graph  →  Frame HTML  →  PNGs  →  video   │
│               (pydantic)      (Playwright)  (ffmpeg)            │
└─────────────────────────────────────────────────────────────────┘
```

---

## Quick start

```bash
# 1. Install Python dependencies
pip install pygments pydantic pyyaml playwright click

# 2. Install the headless browser
python -m playwright install chromium

# 3. Install FFmpeg (via your OS package manager)
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Ubuntu/Debian

# 4. Generate a starter YAML
python termcast.py schema > demo.yaml

# 5. Preview a single scene as a PNG (fast, no video encoding)
python termcast.py preview demo.yaml --scene 0

# 6. Render to video
python termcast.py render demo.yaml -o output.mp4

# Other output formats
python termcast.py render demo.yaml -o output.gif
python termcast.py render demo.yaml -o output.webm

# List all available colour themes
python termcast.py themes
```

---

## How it works — end to end

### 1. YAML → Scene Graph (the parser)

`load_doc()` reads your YAML file with PyYAML's `safe_load`, then constructs typed Pydantic models from the raw dict. Each scene gets its own model class (`ShellScene`, `ReplScene`, `EditorScene`, `TitleScene`, `SplitScene`), all collected under `TermcastDoc`.

Pydantic does schema validation here: if you typo a field name or pass a string where a float is expected, you get a clear error immediately rather than a confusing crash later in the pipeline.

```
YAML text
  └─ yaml.safe_load()  →  raw dict
       └─ load_doc()   →  TermcastDoc
                             ├─ config: GlobalConfig
                             └─ scenes: [ShellScene, ReplScene, EditorScene, ...]
```

### 2. Scene Graph → Frame list (the sequencer)

`sequence_doc()` walks each scene and calls the appropriate `sequence_*_scene()` function. These functions produce a list of `Frame` objects, where each `Frame` holds:

- `html`: a complete, self-contained HTML document string for that moment in time
- `duration`: how many seconds that exact frame should be held for in the video

The sequencer is where all the animation logic lives — typewriter effects, cursor blinking, output appearing line by line, pauses between commands.

**`sequence_shell_scene()`** works like this for each command:

```
1. Blink cursor at empty prompt (~0.4s idle)
2. typewriter_frames() — one Frame per character of the command text
3. Short blink hold (0.25s) — simulates "thinking before Enter"
4. Commit: push the full command line into accumulated_lines[]
5. output_frames() — one Frame per output line appearing
6. Push output lines into accumulated_lines[]
7. Pause frames (pause_after_command duration)
```

`accumulated_lines` is a plain Python list that grows as the scene progresses. Each item is a pre-rendered HTML string for one line of terminal output. The current prompt line sits *outside* this list and is rendered fresh each frame as the typewriter input grows character by character.

**`typewriter_frames()`** converts "ls -la" into a sequence of frames:
`""`, `"l"`, `"ls"`, `"ls "`, `"ls -"`, `"ls -l"`, `"ls -la"`. Each frame duration is the base character delay (derived from `typewriter_wpm`) multiplied by a small hash-derived variance factor so the timing feels human and not mechanical.

**`output_frames()`** works similarly but for output lines: it emits one frame per output line, each time passing an ever-growing list of lines to the render function. The `line_delay` of 40ms per line gives a fast streaming feel.

### 3. Frame HTML → PNG files (the renderer)

`render_frames_to_pngs_numbered()` is the core async loop. It:

1. Launches a headless Chromium browser via Playwright
2. Creates a page with `device_scale_factor=2` — this is the key to high resolution. Chromium renders the page as if it were on a retina display, doubling every pixel. A 1280×720 configured size becomes a 2560×1440 PNG.
3. For each logical Frame, computes an MD5 hash of the HTML string. If that exact HTML has been rendered before, it skips the browser call and just creates another hard link to the existing PNG file.
4. Hard links (`os.link`) instead of file copies mean that a 5-second pause scene that generates 150 identical frames costs 150 directory entries but zero extra disk space or I/O.
5. Output files are named `frame_0000001.png`, `frame_0000002.png`, etc. — the sequential numbering ffmpeg requires.

The MD5 deduplication is important. A 30fps video with 10 seconds of blinking cursor would need 300 Playwright screenshots without it. With it, you need at most 2 (cursor on vs cursor off).

### 4. PNG files → Video (the encoder)

`encode_video()` shells out to `ffmpeg` with format-appropriate flags:

- **MP4** (`libx264`, CRF 12, `slow` preset): CRF 12 is near-lossless for this kind of content. The `slow` preset finds better compression without quality loss.
- **GIF**: Uses ffmpeg's two-pass palette trick — first pass generates an optimal 256-colour palette from the content, second pass dithers the frames against it using Bayer dithering. Much better quality than single-pass GIF encoding.
- **WebM** (`libvpx-vp9`, CRF 10, `b:v 0`): Constant-quality VP9. The `-b:v 0` disables bitrate targeting so CRF is the only quality control.

---

## The HTML rendering system

Every frame is a complete HTML document. `base_html()` is the common template — it sets up a full-bleed `<body>` at exactly `cfg.width × cfg.height` pixels, centres a rounded "window" div inside an outer padding container, and optionally adds the macOS-style window chrome (traffic-light dots + title).

The `_CHROME_` placeholder in the template is replaced by `chrome_html()` output after the fact — a slightly awkward but effective way to inject the chrome string into the `base_html()` output without passing it through every function call.

Each scene type has its own renderer:

- **`render_shell_frame()`**: Renders `accumulated_lines[]` as `<div class="line">` elements plus the current prompt line with the cursor span. The cursor is just a `<span>` with background set to `theme["cursor"]` and foreground set to `theme["bg"]` (so the character under the cursor inverts). `showing_prompt_only=False` is used for the output-appearing phase, where there is no active prompt line yet.

- **`render_repl_frame()`**: Almost identical to shell, but reads the prompt string from `REPL_CONFIGS` (e.g. `">>> "` for Python, `"> "` for Node) and applies the REPL's language to syntax-highlight both input and output.

- **`render_editor_frame()`**: Splits the content string into lines and runs each through `syntax_highlight_html()`. Renders line numbers as fixed-width `<span>` elements. The highlighted lines get a subtle `rgba(255,255,255,0.05)` background. A `<div class="statusbar">` at the bottom shows the vim mode (`-- NORMAL --`, `-- INSERT --`, `-- VISUAL --`), filename, and current line number.

- **`render_title_frame()`**: Vertically centred big text and subtitle. No terminal body.

### Syntax highlighting

`syntax_highlight_html()` feeds the code through Pygments' lexer and walks the token stream manually rather than using Pygments' built-in HTML formatter. This is intentional: the built-in formatter wraps everything in a `<div>` and `<pre>` with class names, which requires injecting a separate CSS class-to-colour mapping. The manual approach lets us inline `style="color:#bb9af7"` directly on each `<span>`, which keeps every frame self-contained and avoids any CSS cascade issues.

Token types are matched by prefix. `Token.Keyword.Declaration` matches the `"Token.Keyword"` key because the key is a prefix of the full type name. This means sub-types correctly inherit their parent's colour when no specific override exists.

---

## YAML reference

### Top-level structure

```yaml
config:       # GlobalConfig — applies to the whole file
  ...

scenes:       # ordered list of scene objects
  - type: shell
    ...
  - type: repl
    ...
```

### `config` (GlobalConfig)

| Field | Type | Default | Description |
|---|---|---|---|
| `theme` | string | `"tokyo-night"` | Colour theme name. See `python termcast.py themes` |
| `font_family` | string | `"JetBrains Mono, Fira Code, Cascadia Code, monospace"` | CSS font-family stack. Fonts must be installed on the system running termcast. |
| `font_size` | int | `16` | Base font size in px (before 2× device scale) |
| `line_height` | float | `1.6` | CSS line-height multiplier |
| `width` | int | `1280` | Frame width in logical px. Output PNG is `width × 2` |
| `height` | int | `720` | Frame height in logical px. Output PNG is `height × 2` |
| `fps` | int | `30` | Frames per second in the output video |
| `padding` | int | `48` | Outer padding (between video edge and window border) |
| `terminal_padding` | int | `20` | Inner padding inside the terminal window |
| `window_chrome` | bool | `true` | Show macOS-style titlebar with traffic-light dots |
| `window_title` | string | `"termcast"` | Text shown in the window titlebar |
| `cursor_blink` | bool | `true` | Whether the cursor blinks (affects idle and pause frames) |
| `typewriter_wpm` | int | `280` | Typing speed in words per minute (1 word = 5 chars) |
| `typewriter_variance` | float | `0.15` | ±variance on char delay as a fraction. 0.15 = ±15% |
| `pause_after_command` | float | `0.6` | Default pause in seconds after each command's output |
| `pause_between_scenes` | float | `1.0` | Pause added after each scene ends |
| `show_timestamps` | bool | `false` | Reserved for future use |

**Resolution guide:**
| `width × height` | Output PNG | Common name |
|---|---|---|
| `960 × 540` | 1920×1080 | 1080p |
| `1280 × 720` | 2560×1440 | 1440p / QHD |
| `1920 × 1080` | 3840×2160 | 4K / UHD |

---

### Scene: `shell`

A bash-style shell session. Commands are typed out with the typewriter effect.

```yaml
- type: shell
  title: ""                 # Window title. Defaults to "user@host: path"
  prompt_user: "user"       # Username in the prompt
  prompt_host: "host"       # Hostname in the prompt
  prompt_path: "~"          # Current directory in the prompt
  theme_override: ""        # Override the global theme for just this scene
  pause_after: -1.0         # Override pause_between_scenes (-1 = use global)
  commands:
    - input: "ls -la"       # The command text (typed out character by character)
      output: |             # What appears after pressing Enter (optional)
        file1.txt
        file2.txt
      delay_before: 0.0     # Extra pause before this command starts typing
      delay_after: -1.0     # Override pause_after_command for this command
      instant_output: false # If true, output appears all at once instead of line by line
      lang: ""              # Force a syntax highlighting language for the output lines
                            # (e.g. lang: python to highlight a script's stdout)
```

The `prompt_user`, `prompt_host`, and `prompt_path` fields control the coloured prompt:
```
user@host:~$
^^^^  ^^^^  ^
│     │     └─ fg colour
│     └───────  prompt_host colour
└─────────────  prompt_user colour (same span as host, separated by @)
               :
               prompt_path (prompt colour)
```

---

### Scene: `repl`

An interactive REPL session. The prompt string and continuation prompt are pulled from `REPL_CONFIGS`.

```yaml
- type: repl
  title: ""           # Window title. Defaults to the REPL name (e.g. "Python 3")
  repl: python        # One of: python, node, ruby, psql, mysql, r, lua, bash
  theme_override: ""
  pause_after: -1.0
  commands:
    - input: "x = 1 + 1"
      output: ""          # Optional. Most statements produce no output
      delay_after: -1.0
      continuation: false # If true, uses the continuation prompt (e.g. "... " in Python)
```

**Available REPLs:**

| `repl` | Prompt | Lang highlight | Title |
|---|---|---|---|
| `python` | `>>> ` | Python | Python 3 |
| `node` | `> ` | JavaScript | Node.js |
| `ruby` | `irb> ` | Ruby | irb |
| `psql` | `=# ` | SQL | psql |
| `mysql` | `mysql> ` | SQL | MySQL |
| `r` | `> ` | R | R |
| `lua` | `> ` | Lua | Lua |
| `bash` | `bash-5.2$ ` | Bash | bash |

---

### Scene: `editor`

A static editor view. Renders a code file with syntax highlighting, line numbers, and a statusbar. Useful for showing a file before or after editing it.

```yaml
- type: editor
  title: ""                 # Window title. Defaults to filename
  mode: vim                 # vim | nano | code
  filename: "main.py"       # Shown in statusbar and used to auto-detect language
  content: |                # Inline file content (use this or content_file, not both)
    def hello():
        print("hi")
  content_file: ""          # Path to a file on disk to read content from
  lang: ""                  # Force syntax highlighting language (overrides filename extension)
  start_line: 1             # Line number to show at the top of the viewport
  highlight_lines: []       # List of line numbers to highlight with a subtle background
  vim_mode: "NORMAL"        # Vim mode shown in statusbar: NORMAL | INSERT | VISUAL | COMMAND
  duration: 3.0             # How many seconds to hold this scene
  theme_override: ""
  pause_after: -1.0
```

**Scrolling:** Set `start_line` to control which part of a long file is visible. The editor renders the full file but CSS `overflow: hidden` clips it — so only lines starting from `start_line` are visible. To simulate scrolling, use multiple consecutive `editor` scenes with different `start_line` values and short `duration`/`pause_after` values.

**Supported `mode` values and their statusbar appearance:**

| `mode` | Statusbar label |
|---|---|
| `vim` | `-- NORMAL --` / `-- INSERT --` / `-- VISUAL --` / `-- COMMAND --` |
| `nano` | `GNU nano` |
| `code` | *(empty — VS Code has no mode label)* |

**Language auto-detection from filename extension:**

`.py` → python, `.js` → javascript, `.ts` → typescript, `.rs` → rust, `.go` → go,
`.c` → c, `.cpp` → cpp, `.java` → java, `.rb` → ruby, `.sh` → bash,
`.yaml`/`.yml` → yaml, `.json` → json, `.html` → html, `.css` → css,
`.md` → markdown, `.sql` → sql, `.r` → r, `.lua` → lua

---

### Scene: `title`

A simple centred title card.

```yaml
- type: title
  text: "My Demo"
  subtitle: "a short description"
  duration: 2.5
  theme_override: ""
  pause_after: -1.0
```

---

### Scene: `split`

Renders multiple panes side by side or stacked. Currently the sequencer animates panes sequentially (one after another) — simultaneous animation across panes is a planned extension.

```yaml
- type: split
  direction: horizontal     # horizontal (side by side) | vertical (top/bottom)
  pause_after: -1.0
  panes:
    - type: shell
      ...
    - type: editor
      ...
```

---

## Themes

Five themes are bundled. Each theme defines terminal colours (`bg`, `fg`, `cursor`, `border`, etc.) plus a `tokens` dict that maps Pygments token types to hex colours.

| Theme | Background | Style |
|---|---|---|
| `tokyo-night` | `#1a1b26` | Dark blue-purple, vivid accents |
| `dracula` | `#282a36` | Classic dark purple, strong contrasts |
| `catppuccin-mocha` | `#1e1e2e` | Soft dark, pastel palette |
| `gruvbox` | `#282828` | Retro brown/gold earthy tones |
| `nord` | `#2e3440` | Muted arctic blues and greens |

### Adding a custom theme

Add an entry to the `THEMES` dict in `termcast.py`:

```python
THEMES["my-theme"] = {
    "bg": "#0d1117",
    "fg": "#e6edf3",
    "cursor": "#e6edf3",
    "prompt": "#58a6ff",
    "prompt_host": "#bc8cff",
    "selection": "#264f78",
    "border": "#30363d",
    "header_bg": "#090c10",
    "header_fg": "#484f58",
    "line_number": "#3d4453",
    "statusbar_bg": "#090c10",
    "statusbar_fg": "#8b949e",
    "statusbar_accent": "#58a6ff",
    "tokens": {
        "keyword": "#ff7b72",
        "keyword_declaration": "#ff7b72",
        "name_function": "#d2a8ff",
        "name_class": "#ffa657",
        "string": "#a5d6ff",
        "string_doc": "#8b949e",
        "number": "#79c0ff",
        "comment": "#8b949e",
        "operator": "#ff7b72",
        "punctuation": "#e6edf3",
        "name_builtin": "#79c0ff",
        "name_decorator": "#ffa657",
        "error": "#f85149",
        "generic_output": "#e6edf3",
        "generic_prompt": "#58a6ff",
    }
}
```

---

## Output format notes

### MP4
Best for most uses. Plays in every browser and video player. Uses H.264 at CRF 12 (near-lossless for this type of content — solid colours and sharp text compress very well). The `slow` preset takes more time but finds better compression, producing smaller files at equal quality.

### GIF
Useful for GitHub READMEs and documentation sites that don't support video. GIF is limited to 256 colours per frame. termcast uses ffmpeg's two-pass palette approach: it first analyses the full video to pick the best 256 colours, then re-encodes using that palette. This gives much better results than single-pass GIF encoding, but the format is still lossy for colour-rich content. For large resolutions and long recordings, GIFs get big fast — consider downscaling `width`/`height` for GIF output.

### WebM
VP9 WebM with alpha channel support (`yuva420p`). Plays in modern browsers and supports transparency if you remove the terminal background. CRF 10 is very high quality. Slightly better compression than MP4 at the same quality level, but slower to encode and less universally supported.

---

## Advanced patterns

### Simulating a long command

Add a `delay_before` to the next command to create a natural pause while a "process" is running:

```yaml
commands:
  - input: "docker build -t myapp ."
    output: |
      [1/5] FROM ubuntu:22.04
      [2/5] RUN apt-get update
      [3/5] COPY . /app
      [4/5] RUN pip install -r requirements.txt
      [5/5] CMD ["python", "app.py"]
      Successfully built a1b2c3d4e5f6
    delay_after: 1.5
```

### Forcing syntax highlighting on output

Use `lang` on the command to highlight output as a specific language:

```yaml
- input: "cat config.yaml"
  output: |
    database:
      host: localhost
      port: 5432
      name: mydb
  lang: yaml
```

### Showing vim editing a long file

Use multiple `editor` scenes with different `start_line` values to simulate scrolling:

```yaml
- type: editor
  mode: vim
  filename: "server.py"
  vim_mode: NORMAL
  start_line: 1
  duration: 1.5
  content: *server_content    # use YAML anchors to avoid repeating

- type: editor
  mode: vim
  filename: "server.py"
  vim_mode: NORMAL
  start_line: 20
  duration: 1.5
  pause_after: 0.0
  content: *server_content

- type: editor
  mode: vim
  filename: "server.py"
  vim_mode: INSERT
  start_line: 35
  highlight_lines: [37, 38]
  duration: 2.0
  content: *server_content
```

### Continuation lines in a REPL

```yaml
- type: repl
  repl: python
  commands:
    - input: "def fib(n):"
    - input: "    if n < 2: return n"
      continuation: true
    - input: "    return fib(n-1) + fib(n-2)"
      continuation: true
    - input: ""
      continuation: true
    - input: "fib(10)"
      output: "55"
```

---

## Performance tips

**Rendering speed** scales with unique frames, not total frames. A 60-second video with 10 seconds of blinking cursor only renders 2 unique cursor frames (on/off), not 600 frames of Playwright screenshots.

**For faster iteration**, use `preview` to check individual scenes before committing to a full render. The `preview` command renders only one frame and skips the video encoding entirely.

**`--keep-frames`** saves the intermediate PNG directory so you can re-encode to different formats without re-rendering:

```bash
python termcast.py render demo.yaml -o out.mp4 --keep-frames --frames-dir ./frames
# Later, re-encode to GIF without re-rendering:
ffmpeg -framerate 30 -i frames/frame_%07d.png -vf "palettegen" palette.png
ffmpeg -framerate 30 -i frames/frame_%07d.png -i palette.png -filter_complex "paletteuse" out.gif
```

---

## Extending termcast

The key extension points are:

- **New scene type**: Add a Pydantic model, a `render_*_frame()` HTML builder, a `sequence_*_scene()` frame producer, and a branch in `sequence_scene()` and `load_doc()`.
- **New theme**: Add an entry to `THEMES` (see above).
- **New REPL**: Add an entry to `REPL_CONFIGS` with `prompt`, `cont_prompt`, `lang`, and `title`.
- **Transitions between scenes**: Add logic in `sequence_doc()` to interpolate frames between scenes (fade, slide, etc.) by blending HTML or inserting intermediate frames.
- **Simultaneous split pane animation**: `sequence_scene()` for `SplitScene` currently animates panes sequentially. True simultaneous animation would require interleaving the frame lists from each pane by timestamp.
- **Actual cursor position in editor**: The editor currently only highlights whole lines. A cursor span could be injected at a specific character offset within a line using `start_line` and a `cursor_col` field.
