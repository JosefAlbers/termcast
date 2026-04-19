#!/usr/bin/env python3
"""
termcast.py — Terminal session to high-res video renderer
Usage:
    python termcast.py render demo.yaml -o output.mp4
    python termcast.py render demo.yaml -o output.gif
    python termcast.py preview demo.yaml          # renders first frame as PNG
    python termcast.py schema                     # print example YAML
"""

from __future__ import annotations
import asyncio, base64, hashlib, json, math, os, shutil, subprocess, sys, tempfile, textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Union
import yaml
from pydantic import BaseModel, Field
from pygments import highlight as pyg_highlight
from pygments.lexers import get_lexer_by_name, guess_lexer
from pygments.formatters import HtmlFormatter
import click

# ─────────────────────────────────────────────
#  THEMES
# ─────────────────────────────────────────────

THEMES: dict[str, dict] = {
    "tokyo-night": {
        "bg": "#1a1b26", "fg": "#cdd6f4", "cursor": "#c0caf5",
        "prompt": "#7aa2f7", "prompt_host": "#bb9af7",
        "selection": "#283457", "border": "#2a2b3d",
        "header_bg": "#13141f", "header_fg": "#565f89",
        "line_number": "#3b4261", "statusbar_bg": "#16161e",
        "statusbar_fg": "#a9b1d6", "statusbar_accent": "#7aa2f7",
        "tokens": {
            "keyword": "#bb9af7", "keyword_declaration": "#bb9af7",
            "name_function": "#7aa2f7", "name_class": "#e0af68",
            "string": "#9ece6a", "string_doc": "#565f89",
            "number": "#ff9e64", "comment": "#565f89",
            "operator": "#89ddff", "punctuation": "#cdd6f4",
            "name_builtin": "#2ac3de", "name_decorator": "#ff9e64",
            "error": "#f7768e", "generic_output": "#a9b1d6",
            "generic_prompt": "#7aa2f7",
        }
    },
    "dracula": {
        "bg": "#282a36", "fg": "#f8f8f2", "cursor": "#f8f8f2",
        "prompt": "#50fa7b", "prompt_host": "#bd93f9",
        "selection": "#44475a", "border": "#44475a",
        "header_bg": "#21222c", "header_fg": "#6272a4",
        "line_number": "#6272a4", "statusbar_bg": "#191a21",
        "statusbar_fg": "#f8f8f2", "statusbar_accent": "#50fa7b",
        "tokens": {
            "keyword": "#ff79c6", "keyword_declaration": "#ff79c6",
            "name_function": "#50fa7b", "name_class": "#f1fa8c",
            "string": "#f1fa8c", "string_doc": "#6272a4",
            "number": "#bd93f9", "comment": "#6272a4",
            "operator": "#ff79c6", "punctuation": "#f8f8f2",
            "name_builtin": "#8be9fd", "name_decorator": "#f1fa8c",
            "error": "#ff5555", "generic_output": "#f8f8f2",
            "generic_prompt": "#50fa7b",
        }
    },
    "catppuccin-mocha": {
        "bg": "#1e1e2e", "fg": "#cdd6f4", "cursor": "#f5e0dc",
        "prompt": "#89b4fa", "prompt_host": "#cba6f7",
        "selection": "#313244", "border": "#313244",
        "header_bg": "#181825", "header_fg": "#585b70",
        "line_number": "#45475a", "statusbar_bg": "#11111b",
        "statusbar_fg": "#cdd6f4", "statusbar_accent": "#89b4fa",
        "tokens": {
            "keyword": "#cba6f7", "keyword_declaration": "#cba6f7",
            "name_function": "#89b4fa", "name_class": "#f9e2af",
            "string": "#a6e3a1", "string_doc": "#585b70",
            "number": "#fab387", "comment": "#585b70",
            "operator": "#89dceb", "punctuation": "#cdd6f4",
            "name_builtin": "#89dceb", "name_decorator": "#f9e2af",
            "error": "#f38ba8", "generic_output": "#cdd6f4",
            "generic_prompt": "#89b4fa",
        }
    },
    "gruvbox": {
        "bg": "#282828", "fg": "#ebdbb2", "cursor": "#ebdbb2",
        "prompt": "#b8bb26", "prompt_host": "#fabd2f",
        "selection": "#3c3836", "border": "#504945",
        "header_bg": "#1d2021", "header_fg": "#928374",
        "line_number": "#504945", "statusbar_bg": "#1d2021",
        "statusbar_fg": "#ebdbb2", "statusbar_accent": "#b8bb26",
        "tokens": {
            "keyword": "#fb4934", "keyword_declaration": "#fb4934",
            "name_function": "#b8bb26", "name_class": "#fabd2f",
            "string": "#b8bb26", "string_doc": "#928374",
            "number": "#d3869b", "comment": "#928374",
            "operator": "#8ec07c", "punctuation": "#ebdbb2",
            "name_builtin": "#83a598", "name_decorator": "#fabd2f",
            "error": "#fb4934", "generic_output": "#ebdbb2",
            "generic_prompt": "#b8bb26",
        }
    },
    "nord": {
        "bg": "#2e3440", "fg": "#d8dee9", "cursor": "#d8dee9",
        "prompt": "#88c0d0", "prompt_host": "#81a1c1",
        "selection": "#3b4252", "border": "#3b4252",
        "header_bg": "#272c36", "header_fg": "#616e88",
        "line_number": "#4c566a", "statusbar_bg": "#232730",
        "statusbar_fg": "#d8dee9", "statusbar_accent": "#88c0d0",
        "tokens": {
            "keyword": "#81a1c1", "keyword_declaration": "#81a1c1",
            "name_function": "#88c0d0", "name_class": "#8fbcbb",
            "string": "#a3be8c", "string_doc": "#616e88",
            "number": "#b48ead", "comment": "#616e88",
            "operator": "#81a1c1", "punctuation": "#d8dee9",
            "name_builtin": "#8fbcbb", "name_decorator": "#ebcb8b",
            "error": "#bf616a", "generic_output": "#d8dee9",
            "generic_prompt": "#88c0d0",
        }
    },
}

REPL_CONFIGS = {
    "python": {"prompt": ">>> ", "cont_prompt": "... ", "lang": "python3", "title": "Python 3"},
    "node":   {"prompt": "> ",   "cont_prompt": "... ", "lang": "javascript", "title": "Node.js"},
    "ruby":   {"prompt": "irb> ","cont_prompt": "irb> ","lang": "ruby", "title": "irb"},
    "psql":   {"prompt": "=# ",  "cont_prompt": "-# ",  "lang": "sql", "title": "psql"},
    "mysql":  {"prompt": "mysql> ","cont_prompt": "    -> ","lang": "sql", "title": "MySQL"},
    "r":      {"prompt": "> ",   "cont_prompt": "+ ",   "lang": "r", "title": "R"},
    "lua":    {"prompt": "> ",   "cont_prompt": ">> ",  "lang": "lua", "title": "Lua"},
    "bash":   {"prompt": "bash-5.2$ ","cont_prompt": "> ","lang": "bash", "title": "bash"},
}

# ─────────────────────────────────────────────
#  PYDANTIC SCHEMA
# ─────────────────────────────────────────────

class GlobalConfig(BaseModel):
    theme: str = "tokyo-night"
    font_family: str = "JetBrains Mono, Fira Code, Cascadia Code, monospace"
    font_size: int = 16
    line_height: float = 1.6
    width: int = 1280
    height: int = 720
    fps: int = 30
    padding: int = 48
    terminal_padding: int = 20
    window_chrome: bool = True
    window_title: str = "termcast"
    cursor_blink: bool = True
    typewriter_wpm: int = 280
    typewriter_variance: float = 0.15
    pause_after_command: float = 0.6
    pause_between_scenes: float = 1.0
    show_timestamps: bool = False

class ShellCommand(BaseModel):
    input: str
    output: str = ""
    delay_before: float = 0.0
    delay_after: float = -1.0  # -1 = use global default
    instant_output: bool = False
    lang: str = ""            # force syntax lang for output

class ShellScene(BaseModel):
    type: Literal["shell"] = "shell"
    title: str = ""
    prompt_user: str = "user"
    prompt_host: str = "host"
    prompt_path: str = "~"
    commands: list[ShellCommand] = []
    theme_override: str = ""
    show_line_numbers: bool = False
    pause_after: float = -1.0

class ReplCommand(BaseModel):
    input: str
    output: str = ""
    delay_after: float = -1.0
    continuation: bool = False

class ReplScene(BaseModel):
    type: Literal["repl"] = "repl"
    title: str = ""
    repl: str = "python"
    commands: list[ReplCommand] = []
    theme_override: str = ""
    pause_after: float = -1.0

class EditorScene(BaseModel):
    type: Literal["editor"] = "editor"
    title: str = ""
    mode: Literal["vim", "nano", "code"] = "vim"
    filename: str = "untitled.txt"
    content: str = ""
    content_file: str = ""
    lang: str = ""
    start_line: int = 1
    highlight_lines: list[int] = []
    vim_mode: str = "NORMAL"
    duration: float = 3.0
    theme_override: str = ""
    pause_after: float = -1.0

class SplitScene(BaseModel):
    type: Literal["split"] = "split"
    title: str = ""
    direction: Literal["horizontal", "vertical"] = "horizontal"
    panes: list[Union[ShellScene, ReplScene, EditorScene]] = []
    pause_after: float = -1.0

class TitleScene(BaseModel):
    type: Literal["title"] = "title"
    text: str = ""
    subtitle: str = ""
    duration: float = 2.5
    theme_override: str = ""
    pause_after: float = -1.0

AnyScene = Union[ShellScene, ReplScene, EditorScene, SplitScene, TitleScene]

class TermcastDoc(BaseModel):
    config: GlobalConfig = Field(default_factory=GlobalConfig)
    scenes: list[AnyScene] = []

# ─────────────────────────────────────────────
#  SYNTAX HIGHLIGHTING
# ─────────────────────────────────────────────

def syntax_highlight_html(code: str, lang: str, theme_tokens: dict) -> str:
    """Returns an HTML string with <span> tags for syntax highlighting."""
    try:
        lexer = get_lexer_by_name(lang, stripall=False)
    except Exception:
        try:
            lexer = guess_lexer(code)
        except Exception:
            return code.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    from pygments.token import Token
    from pygments import lex

    TOKEN_MAP = {
        "Token.Keyword": "keyword",
        "Token.Keyword.Declaration": "keyword_declaration",
        "Token.Keyword.Namespace": "keyword",
        "Token.Keyword.Type": "keyword",
        "Token.Name.Function": "name_function",
        "Token.Name.Class": "name_class",
        "Token.Name.Builtin": "name_builtin",
        "Token.Name.Decorator": "name_decorator",
        "Token.Literal.String": "string",
        "Token.Literal.String.Doc": "string_doc",
        "Token.Literal.Number": "number",
        "Token.Literal.Number.Integer": "number",
        "Token.Literal.Number.Float": "number",
        "Token.Comment": "comment",
        "Token.Comment.Single": "comment",
        "Token.Comment.Multiline": "comment",
        "Token.Operator": "operator",
        "Token.Punctuation": "punctuation",
        "Token.Generic.Output": "generic_output",
        "Token.Generic.Prompt": "generic_prompt",
        "Token.Error": "error",
    }

    result = []
    for ttype, value in lex(code, lexer):
        value_esc = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        key = str(ttype)
        color = None
        # Walk up the token type hierarchy
        for map_key, tok_name in TOKEN_MAP.items():
            if key.startswith(map_key.replace("Token.", "")):
                color = theme_tokens.get(tok_name)
                break
        if not color:
            # try direct match
            color = theme_tokens.get(TOKEN_MAP.get(key, ""), None)
        if color:
            result.append(f'<span style="color:{color}">{value_esc}</span>')
        else:
            result.append(value_esc)
    return "".join(result)

# ─────────────────────────────────────────────
#  HTML FRAME BUILDERS
# ─────────────────────────────────────────────

def base_html(cfg: GlobalConfig, theme: dict, body: str, extra_style: str = "") -> str:
    bg = theme["bg"]
    fg = theme["fg"]
    font = cfg.font_family
    fs = cfg.font_size
    lh = cfg.line_height
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{
    width: {cfg.width}px; height: {cfg.height}px;
    background: {bg}; color: {fg};
    font-family: {font};
    font-size: {fs}px; line-height: {lh};
    overflow: hidden;
  }}
  .outer {{
    width: 100%; height: 100%;
    display: flex; align-items: center; justify-content: center;
    padding: {cfg.padding}px;
  }}
  .window {{
    width: 100%; height: 100%;
    background: {bg};
    border: 1px solid {theme['border']};
    border-radius: 10px;
    display: flex; flex-direction: column;
    overflow: hidden;
  }}
  .chrome {{
    background: {theme['header_bg']};
    padding: 10px 16px;
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid {theme['border']};
    flex-shrink: 0;
  }}
  .dot {{ width: 13px; height: 13px; border-radius: 50%; }}
  .dot-r {{ background: #ff5f57; }}
  .dot-y {{ background: #ffbd2e; }}
  .dot-g {{ background: #28c941; }}
  .chrome-title {{ color: {theme['header_fg']}; font-size: 13px; margin: 0 auto; }}
  .content {{
    flex: 1; overflow: hidden;
    padding: {cfg.terminal_padding}px;
  }}
  {extra_style}
</style>
</head>
<body>
<div class="outer">
  <div class="window">
    {"_CHROME_" if cfg.window_chrome else ""}
    <div class="content">{body}</div>
  </div>
</div>
</body>
</html>"""

def chrome_html(title: str, theme: dict) -> str:
    return f"""<div class="chrome">
  <div class="dot dot-r"></div>
  <div class="dot dot-y"></div>
  <div class="dot dot-g"></div>
  <div class="chrome-title">{title}</div>
</div>"""

def make_prompt_html(scene: ShellScene, theme: dict) -> str:
    pc = theme["prompt"]
    hc = theme["prompt_host"]
    fg = theme["fg"]
    return (f'<span style="color:{hc}">{scene.prompt_user}@{scene.prompt_host}</span>'
            f'<span style="color:{fg}">:</span>'
            f'<span style="color:{pc}">{scene.prompt_path}</span>'
            f'<span style="color:{fg}">$ </span>')

def render_shell_frame(
    cfg: GlobalConfig,
    theme: dict,
    scene: ShellScene,
    lines: list[str],   # already-rendered HTML lines
    show_cursor: bool = True,
    partial_input: str = "",
    showing_prompt_only: bool = False,
) -> str:
    prompt_html = make_prompt_html(scene, theme)
    cursor_html = f'<span style="background:{theme["cursor"]};color:{theme["bg"]}"> </span>' if show_cursor else ""

    lines_html = "".join(f'<div class="line">{l}</div>' for l in lines)

    if showing_prompt_only:
        current = f'<div class="line">{prompt_html}{partial_input}{cursor_html}</div>'
    else:
        current = ""

    body = f'<div class="terminal-body">{lines_html}{current}</div>'

    title = scene.title or f"{scene.prompt_user}@{scene.prompt_host}: {scene.prompt_path}"
    chrome = chrome_html(title, theme) if cfg.window_chrome else ""

    extra = """
    .terminal-body { height: 100%; overflow: hidden; }
    .line { white-space: pre-wrap; word-break: break-all; min-height: 1.1em; }
    """
    html = base_html(cfg, theme, body, extra)
    return html.replace("_CHROME_", chrome)

def render_repl_frame(
    cfg: GlobalConfig,
    theme: dict,
    scene: ReplScene,
    lines: list[str],
    show_cursor: bool = True,
    partial_input: str = "",
    showing_prompt: bool = True,
) -> str:
    rc = REPL_CONFIGS.get(scene.repl, REPL_CONFIGS["python"])
    pc = theme["prompt"]
    cursor_html = f'<span style="background:{theme["cursor"]};color:{theme["bg"]}"> </span>' if show_cursor else ""
    prompt_html = f'<span style="color:{pc}">{rc["prompt"]}</span>'

    lines_html = "".join(f'<div class="line">{l}</div>' for l in lines)
    current = f'<div class="line">{prompt_html}{partial_input}{cursor_html}</div>' if showing_prompt else ""

    body = f'<div class="terminal-body">{lines_html}{current}</div>'

    title = scene.title or rc["title"]
    chrome = chrome_html(title, theme) if cfg.window_chrome else ""

    extra = ".terminal-body { height: 100%; overflow: hidden; } .line { white-space: pre-wrap; word-break: break-all; min-height: 1.1em; }"
    html = base_html(cfg, theme, body, extra)
    return html.replace("_CHROME_", chrome)

def render_editor_frame(cfg: GlobalConfig, theme: dict, scene: EditorScene) -> str:
    content = scene.content
    if scene.content_file and Path(scene.content_file).exists():
        content = Path(scene.content_file).read_text()

    lang = scene.lang
    if not lang and scene.filename:
        ext_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".rs": "rust", ".go": "go", ".c": "c", ".cpp": "cpp",
            ".java": "java", ".rb": "ruby", ".sh": "bash", ".yaml": "yaml",
            ".yml": "yaml", ".json": "json", ".html": "html", ".css": "css",
            ".md": "markdown", ".sql": "sql", ".r": "r", ".lua": "lua",
        }
        ext = Path(scene.filename).suffix.lower()
        lang = ext_map.get(ext, "text")

    lines = content.split("\n")
    ln_width = len(str(len(lines) + scene.start_line))

    highlighted_lines = []
    for i, line in enumerate(lines):
        ln = i + scene.start_line
        hl = syntax_highlight_html(line, lang, theme["tokens"])
        is_hl = (ln in scene.highlight_lines)
        bg = f'background:rgba(255,255,255,0.05);' if is_hl else ""
        lnum_color = theme["line_number"]
        lnum = f'<span style="color:{lnum_color};user-select:none;margin-right:16px;text-align:right;display:inline-block;width:{ln_width}ch">{ln}</span>'
        highlighted_lines.append(f'<div class="line" style="{bg}">{lnum}{hl}</div>')

    lines_html = "".join(highlighted_lines)

    # statusbar
    sb_bg = theme["statusbar_bg"]
    sb_fg = theme["statusbar_fg"]
    sb_ac = theme["statusbar_accent"]
    mode_label = {"vim": f"-- {scene.vim_mode} --", "nano": "GNU nano", "code": ""}[scene.mode]
    statusbar = f"""
    <div class="statusbar">
      <span style="color:{sb_ac};font-weight:500">{mode_label}</span>
      <span style="margin-left:auto;color:{sb_fg}">{scene.filename}</span>
      <span style="margin-left:16px;color:{sb_fg}">Ln {scene.start_line}</span>
    </div>"""

    body = f'<div class="editor-wrap"><div class="editor-content">{lines_html}</div>{statusbar}</div>'
    title = scene.title or scene.filename
    chrome = chrome_html(title, theme) if cfg.window_chrome else ""

    extra = f"""
    .editor-wrap {{ height: 100%; display: flex; flex-direction: column; }}
    .editor-content {{ flex: 1; overflow: hidden; }}
    .line {{ white-space: pre; min-height: 1.1em; }}
    .statusbar {{
      flex-shrink: 0; display: flex; align-items: center;
      background: {sb_bg}; padding: 4px 12px; font-size: 0.88em;
      border-top: 1px solid {theme['border']};
    }}
    """
    html = base_html(cfg, theme, body, extra)
    return html.replace("_CHROME_", chrome)

def render_title_frame(cfg: GlobalConfig, theme: dict, scene: TitleScene) -> str:
    fg = theme["fg"]
    ac = theme["prompt"]
    body = f"""
    <div style="height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:16px;">
      <div style="font-size:{cfg.font_size*2.2:.0f}px;font-weight:600;color:{fg};text-align:center">{scene.text}</div>
      <div style="font-size:{cfg.font_size*1.1:.0f}px;color:{ac};text-align:center">{scene.subtitle}</div>
    </div>"""
    chrome = chrome_html(cfg.window_title, theme) if cfg.window_chrome else ""
    html = base_html(cfg, theme, body)
    return html.replace("_CHROME_", chrome)

# ─────────────────────────────────────────────
#  FRAME SEQUENCER
# ─────────────────────────────────────────────

@dataclass
class Frame:
    html: str
    duration: float  # seconds

def get_theme(cfg: GlobalConfig, override: str = "") -> dict:
    name = override or cfg.theme
    t = THEMES.get(name, THEMES["tokyo-night"])
    return t

def typewriter_frames(
    cfg: GlobalConfig,
    text: str,
    make_frame_fn,   # fn(partial: str, cursor: bool) -> Frame
    wpm: int = 0,
) -> list[Frame]:
    wpm = wpm or cfg.typewriter_wpm
    char_delay = 60.0 / (wpm * 5)
    frames = []
    for i in range(len(text) + 1):
        partial = text[:i]
        dur = char_delay * (1 + (hash(partial) % 100 - 50) / 100 * cfg.typewriter_variance)
        dur = max(0.01, dur)
        html = make_frame_fn(partial, True)
        frames.append(Frame(html, dur))
    return frames

def output_frames(
    cfg: GlobalConfig,
    output_text: str,
    make_frame_fn,   # fn(lines_so_far: list[str]) -> str (html)
    base_lines: list[str],
    lang: str = "",
    theme: dict = None,
    instant: bool = False,
) -> list[Frame]:
    if not output_text.strip():
        return []
    frames = []
    raw_lines = output_text.rstrip("\n").split("\n")
    line_delay = 0.04 if not instant else 0.0

    for i in range(1, len(raw_lines) + 1):
        out_lines = []
        for l in raw_lines[:i]:
            if lang and theme:
                out_lines.append(syntax_highlight_html(l, lang, theme["tokens"]))
            else:
                out_lines.append(l.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        html = make_frame_fn(base_lines + out_lines)
        frames.append(Frame(html, line_delay if not instant else 0.016))
    return frames

def sequence_shell_scene(cfg: GlobalConfig, scene: ShellScene) -> list[Frame]:
    theme = get_theme(cfg, scene.theme_override)
    frames = []
    accumulated_lines: list[str] = []
    prompt_html = make_prompt_html(scene, theme)

    def make_typing_frame(partial: str, cursor: bool) -> str:
        return render_shell_frame(cfg, theme, scene, accumulated_lines,
                                   show_cursor=cursor, partial_input=partial,
                                   showing_prompt_only=True)

    def make_output_frame(lines: list[str]) -> str:
        return render_shell_frame(cfg, theme, scene, lines, show_cursor=False,
                                   showing_prompt_only=False)

    # idle cursor blink at start
    for _ in range(int(cfg.fps * 0.4)):
        blink = (_ % (cfg.fps // 2)) < (cfg.fps // 4)
        frames.append(Frame(render_shell_frame(cfg, theme, scene, accumulated_lines,
                                                show_cursor=blink, showing_prompt_only=True,
                                                partial_input=""), 1.0 / cfg.fps))

    for cmd in scene.commands:
        if cmd.delay_before > 0:
            for _ in range(int(cmd.delay_before * cfg.fps)):
                frames.append(Frame(make_typing_frame("", True), 1.0 / cfg.fps))

        # typewriter input
        frames += typewriter_frames(cfg, cmd.input, make_typing_frame)

        # hold after typing (cursor blink before enter)
        for i in range(int(cfg.fps * 0.25)):
            blink = (i % (cfg.fps // 2)) < (cfg.fps // 4)
            frames.append(Frame(make_typing_frame(cmd.input, blink), 1.0 / cfg.fps))

        # show the completed command line in accumulated
        cmd_html = prompt_html + syntax_highlight_html(cmd.input, "bash", theme["tokens"])
        accumulated_lines.append(cmd_html)

        # output
        if cmd.output:
            out_lang = cmd.lang or ""
            frames += output_frames(cfg, cmd.output,
                                     make_output_frame,
                                     accumulated_lines[:],
                                     lang=out_lang, theme=theme,
                                     instant=cmd.instant_output)
            raw_out = cmd.output.rstrip("\n").split("\n")
            for l in raw_out:
                if out_lang and theme:
                    accumulated_lines.append(syntax_highlight_html(l, out_lang, theme["tokens"]))
                else:
                    accumulated_lines.append(l.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;"))

        # pause after command
        pause = cmd.delay_after if cmd.delay_after >= 0 else cfg.pause_after_command
        for i in range(int(pause * cfg.fps)):
            blink = (i % (cfg.fps // 2)) < (cfg.fps // 4)
            frames.append(Frame(make_typing_frame("", blink), 1.0 / cfg.fps))

    # final pause
    scene_pause = scene.pause_after if scene.pause_after >= 0 else cfg.pause_between_scenes
    for i in range(int(scene_pause * cfg.fps)):
        frames.append(Frame(make_typing_frame("", False), 1.0 / cfg.fps))

    return frames

def sequence_repl_scene(cfg: GlobalConfig, scene: ReplScene) -> list[Frame]:
    theme = get_theme(cfg, scene.theme_override)
    rc = REPL_CONFIGS.get(scene.repl, REPL_CONFIGS["python"])
    frames = []
    accumulated_lines: list[str] = []
    pc = theme["prompt"]

    def make_typing_frame(partial: str, cursor: bool) -> str:
        return render_repl_frame(cfg, theme, scene, accumulated_lines,
                                  show_cursor=cursor, partial_input=partial,
                                  showing_prompt=True)

    def make_output_frame(lines: list[str]) -> str:
        return render_repl_frame(cfg, theme, scene, lines,
                                  show_cursor=False, showing_prompt=False)

    for _ in range(int(cfg.fps * 0.4)):
        frames.append(Frame(make_typing_frame("", True), 1.0 / cfg.fps))

    for cmd in scene.commands:
        frames += typewriter_frames(cfg, cmd.input, make_typing_frame)

        for i in range(int(cfg.fps * 0.2)):
            blink = (i % (cfg.fps // 2)) < (cfg.fps // 4)
            frames.append(Frame(make_typing_frame(cmd.input, blink), 1.0 / cfg.fps))

        prompt_label = rc["cont_prompt"] if cmd.continuation else rc["prompt"]
        cmd_html = (f'<span style="color:{pc}">{prompt_label}</span>'
                    + syntax_highlight_html(cmd.input, rc["lang"], theme["tokens"]))
        accumulated_lines.append(cmd_html)

        if cmd.output:
            frames += output_frames(cfg, cmd.output, make_output_frame,
                                     accumulated_lines[:],
                                     lang=rc["lang"], theme=theme)
            for l in cmd.output.rstrip("\n").split("\n"):
                fg = theme["fg"]
                accumulated_lines.append(f'<span style="color:{fg}">{l}</span>')

        pause = cmd.delay_after if cmd.delay_after >= 0 else cfg.pause_after_command
        for i in range(int(pause * cfg.fps)):
            blink = (i % (cfg.fps // 2)) < (cfg.fps // 4)
            frames.append(Frame(make_typing_frame("", blink), 1.0 / cfg.fps))

    scene_pause = scene.pause_after if scene.pause_after >= 0 else cfg.pause_between_scenes
    for i in range(int(scene_pause * cfg.fps)):
        frames.append(Frame(make_typing_frame("", False), 1.0 / cfg.fps))

    return frames

def sequence_editor_scene(cfg: GlobalConfig, scene: EditorScene) -> list[Frame]:
    theme = get_theme(cfg, scene.theme_override)
    html = render_editor_frame(cfg, theme, scene)
    frames = []
    n = max(1, int(scene.duration * cfg.fps))
    for _ in range(n):
        frames.append(Frame(html, 1.0 / cfg.fps))
    scene_pause = scene.pause_after if scene.pause_after >= 0 else cfg.pause_between_scenes
    for _ in range(int(scene_pause * cfg.fps)):
        frames.append(Frame(html, 1.0 / cfg.fps))
    return frames

def sequence_title_scene(cfg: GlobalConfig, scene: TitleScene) -> list[Frame]:
    theme = get_theme(cfg, scene.theme_override)
    html = render_title_frame(cfg, theme, scene)
    n = max(1, int(scene.duration * cfg.fps))
    frames = [Frame(html, 1.0 / cfg.fps)] * n
    scene_pause = scene.pause_after if scene.pause_after >= 0 else cfg.pause_between_scenes
    frames += [Frame(html, 1.0 / cfg.fps)] * int(scene_pause * cfg.fps)
    return frames

def sequence_scene(cfg: GlobalConfig, scene: AnyScene) -> list[Frame]:
    if isinstance(scene, ShellScene):
        return sequence_shell_scene(cfg, scene)
    elif isinstance(scene, ReplScene):
        return sequence_repl_scene(cfg, scene)
    elif isinstance(scene, EditorScene):
        return sequence_editor_scene(cfg, scene)
    elif isinstance(scene, TitleScene):
        return sequence_title_scene(cfg, scene)
    elif isinstance(scene, SplitScene):
        # For split scenes, just render first pane for now (MVP)
        if scene.panes:
            return sequence_scene(cfg, scene.panes[0])
        return []
    return []

def sequence_doc(doc: TermcastDoc) -> list[Frame]:
    all_frames = []
    for scene in doc.scenes:
        all_frames += sequence_scene(doc.config, scene)
    return all_frames

# ─────────────────────────────────────────────
#  RENDERER (Playwright)
# ─────────────────────────────────────────────

async def render_frames_to_pngs(frames: list[Frame], out_dir: Path, cfg: GlobalConfig,
                                  progress_cb=None) -> list[Path]:
    from playwright.async_api import async_playwright

    paths = []
    # Deduplicate: same HTML -> same PNG
    html_to_path: dict[str, Path] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": cfg.width, "height": cfg.height},
                                       device_scale_factor=2)  # 2x = retina quality

        for i, frame in enumerate(frames):
            h = hashlib.md5(frame.html.encode()).hexdigest()
            if h in html_to_path:
                paths.append(html_to_path[h])
            else:
                png_path = out_dir / f"frame_{i:06d}_src.png"
                await page.set_content(frame.html, wait_until="domcontentloaded")
                await page.screenshot(path=str(png_path), full_page=False,
                                       clip={"x": 0, "y": 0,
                                             "width": cfg.width, "height": cfg.height})
                html_to_path[h] = png_path
                paths.append(png_path)

            if progress_cb:
                progress_cb(i + 1, len(frames))

        await browser.close()

    return paths

async def render_frames_to_pngs_numbered(frames: list[Frame], out_dir: Path,
                                          cfg: GlobalConfig, progress_cb=None) -> int:
    """Render frames to sequentially numbered PNGs for ffmpeg."""
    from playwright.async_api import async_playwright

    html_to_path: dict[str, Path] = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(
            viewport={"width": cfg.width, "height": cfg.height},
            device_scale_factor=2)

        frame_num = 0
        for i, frame in enumerate(frames):
            # expand frame duration to actual frame count
            n_frames = max(1, round(frame.duration * cfg.fps))
            h = hashlib.md5(frame.html.encode()).hexdigest()

            if h not in html_to_path:
                src_path = out_dir / f"src_{h}.png"
                await page.set_content(frame.html, wait_until="domcontentloaded")
                await page.screenshot(path=str(src_path), full_page=False,
                                       clip={"x": 0, "y": 0,
                                             "width": cfg.width * 2,
                                             "height": cfg.height * 2})
                html_to_path[h] = src_path

            src = html_to_path[h]
            for _ in range(n_frames):
                dst = out_dir / f"frame_{frame_num:07d}.png"
                os.link(src, dst)  # hard link to avoid copying
                frame_num += 1

            if progress_cb:
                progress_cb(i + 1, len(frames))

        await browser.close()

    return frame_num

# ─────────────────────────────────────────────
#  VIDEO ENCODER
# ─────────────────────────────────────────────

def encode_video(frame_dir: Path, output_path: Path, cfg: GlobalConfig,
                  total_frames: int) -> None:
    ext = output_path.suffix.lower()
    # frames are 2x resolution due to device_scale_factor=2
    actual_w = cfg.width * 2
    actual_h = cfg.height * 2

    if ext == ".gif":
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(cfg.fps),
            "-i", str(frame_dir / "frame_%07d.png"),
            "-vf", (f"scale={actual_w}:{actual_h}:flags=lanczos,"
                    f"split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=bayer"),
            str(output_path)
        ]
    elif ext in (".webm",):
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(cfg.fps),
            "-i", str(frame_dir / "frame_%07d.png"),
            "-c:v", "libvpx-vp9",
            "-crf", "10", "-b:v", "0",
            "-pix_fmt", "yuva420p",
            str(output_path)
        ]
    else:  # mp4 default
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(cfg.fps),
            "-i", str(frame_dir / "frame_%07d.png"),
            "-c:v", "libx264",
            "-crf", "12",
            "-preset", "slow",
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={actual_w}:{actual_h}",
            str(output_path)
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg error:\n{result.stderr}")

# ─────────────────────────────────────────────
#  YAML LOADER
# ─────────────────────────────────────────────

def load_doc(path: str) -> TermcastDoc:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise ValueError("YAML must be a mapping at the top level")

    config_raw = raw.get("config", {})
    config = GlobalConfig(**config_raw)

    scenes = []
    for s in raw.get("scenes", []):
        t = s.get("type", "shell")
        if t == "shell":
            scenes.append(ShellScene(**s))
        elif t == "repl":
            scenes.append(ReplScene(**s))
        elif t == "editor":
            scenes.append(EditorScene(**s))
        elif t == "title":
            scenes.append(TitleScene(**s))
        elif t == "split":
            panes = []
            for p in s.get("panes", []):
                pt = p.get("type", "shell")
                if pt == "shell": panes.append(ShellScene(**p))
                elif pt == "repl": panes.append(ReplScene(**p))
                elif pt == "editor": panes.append(EditorScene(**p))
            scenes.append(SplitScene(**{**s, "panes": panes}))
        else:
            click.echo(f"Warning: unknown scene type '{t}', skipping", err=True)

    return TermcastDoc(config=config, scenes=scenes)

# ─────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────

EXAMPLE_YAML = """\
config:
  theme: tokyo-night          # tokyo-night | dracula | catppuccin-mocha | gruvbox | nord
  font_family: "JetBrains Mono, Fira Code, monospace"
  font_size: 16
  width: 1920
  height: 1080
  fps: 30
  padding: 52
  typewriter_wpm: 260
  pause_after_command: 0.7
  window_title: "demo"

scenes:
  - type: title
    text: "termcast demo"
    subtitle: "high-res terminal recordings"
    duration: 2.0

  - type: shell
    prompt_user: alice
    prompt_host: dev
    prompt_path: "~/projects/demo"
    commands:
      - input: "ls -la"
        output: |
          total 48
          drwxr-xr-x  6 alice staff  192 Apr 19 10:22 .
          drwxr-xr-x 12 alice staff  384 Apr 18 09:01 ..
          -rw-r--r--  1 alice staff 1.2K Apr 19 10:22 README.md
          -rw-r--r--  1 alice staff 4.5K Apr 19 10:20 train.py
          drwxr-xr-x  4 alice staff  128 Apr 17 14:30 data

      - input: "python train.py --epochs 5 --lr 0.001"
        output: |
          Loading dataset... 60000 samples
          Epoch 1/5: loss=0.8421  acc=0.7134
          Epoch 2/5: loss=0.6103  acc=0.8012
          Epoch 3/5: loss=0.4872  acc=0.8541
          Epoch 4/5: loss=0.3901  acc=0.8830
          Epoch 5/5: loss=0.3211  acc=0.9012
          Saved model to ./checkpoints/model.pt
        delay_after: 1.5

  - type: repl
    repl: python
    title: "Python 3.12"
    commands:
      - input: "import torch"
      - input: "x = torch.randn(4, 4)"
      - input: "x.shape"
        output: "torch.Size([4, 4])"
      - input: "x.mean().item()"
        output: "0.12345670163631439"

  - type: editor
    mode: vim
    filename: "train.py"
    lang: python
    vim_mode: NORMAL
    duration: 3.5
    highlight_lines: [12, 13, 14]
    content: |
      import torch
      import torch.nn as nn
      from torch.utils.data import DataLoader

      class SimpleNet(nn.Module):
          def __init__(self, input_dim, hidden, output_dim):
              super().__init__()
              self.layers = nn.Sequential(
                  nn.Linear(input_dim, hidden),
                  nn.ReLU(),
                  nn.Linear(hidden, output_dim)
              )

          def forward(self, x):
              return self.layers(x)

      def train(model, loader, optimizer, criterion):
          model.train()
          for batch_x, batch_y in loader:
              optimizer.zero_grad()
              loss = criterion(model(batch_x), batch_y)
              loss.backward()
              optimizer.step()
"""

@click.group()
def cli():
    """termcast — render terminal sessions to high-res video"""
    pass

@cli.command()
@click.argument("input_file")
@click.option("-o", "--output", default="output.mp4", help="Output file (.mp4, .gif, .webm)")
@click.option("--keep-frames", is_flag=True, help="Keep intermediate PNG frames")
@click.option("--frames-dir", default="", help="Custom directory for frames")
def render(input_file, output, keep_frames, frames_dir):
    """Render a YAML session file to video."""
    click.echo(f"Loading {input_file}...")
    doc = load_doc(input_file)
    cfg = doc.config

    click.echo(f"Sequencing {len(doc.scenes)} scene(s)...")
    frames = sequence_doc(doc)
    total_duration = sum(f.duration for f in frames)
    # actual rendered frame count
    actual_frames = sum(max(1, round(f.duration * cfg.fps)) for f in frames)
    click.echo(f"  → {len(frames)} logical frames → {actual_frames} video frames "
               f"({total_duration:.1f}s at {cfg.fps}fps)")

    tmp_dir = Path(frames_dir) if frames_dir else Path(tempfile.mkdtemp(prefix="termcast_"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Rendering frames to {tmp_dir} ...")
    with click.progressbar(length=len(frames), label="Rendering") as bar:
        last = [0]
        def progress(done, total):
            bar.update(done - last[0])
            last[0] = done

        n = asyncio.run(render_frames_to_pngs_numbered(frames, tmp_dir, cfg, progress))

    click.echo(f"Encoding {n} frames → {output} ...")
    encode_video(tmp_dir, Path(output), cfg, n)

    if not keep_frames:
        shutil.rmtree(tmp_dir)

    out_size = Path(output).stat().st_size / 1024 / 1024
    click.echo(f"Done! {output} ({out_size:.1f} MB, {cfg.width*2}×{cfg.height*2} px)")

@cli.command()
@click.argument("input_file")
@click.option("-o", "--output", default="preview.png", help="Output PNG path")
@click.option("--scene", default=0, help="Scene index to preview")
def preview(input_file, output, scene):
    """Render the first frame of a scene as a PNG."""
    doc = load_doc(input_file)
    cfg = doc.config

    if scene >= len(doc.scenes):
        click.echo(f"Error: scene {scene} out of range (doc has {len(doc.scenes)} scenes)")
        sys.exit(1)

    s = doc.scenes[scene]
    click.echo(f"Previewing scene {scene} ({s.type})...")
    frames = sequence_scene(cfg, s)
    if not frames:
        click.echo("No frames generated for this scene.")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        async def _render():
            from playwright.async_api import async_playwright
            async with async_playwright() as pw:
                browser = await pw.chromium.launch()
                page = await browser.new_page(
                    viewport={"width": cfg.width, "height": cfg.height},
                    device_scale_factor=2)
                await page.set_content(frames[0].html, wait_until="domcontentloaded")
                await page.screenshot(path=output, full_page=False,
                                       clip={"x": 0, "y": 0,
                                             "width": cfg.width, "height": cfg.height})
                await browser.close()

        asyncio.run(_render())

    size = Path(output).stat().st_size / 1024
    click.echo(f"Saved {output} ({size:.0f} KB, {cfg.width*2}×{cfg.height*2})")

@cli.command()
def schema():
    """Print an example YAML session file."""
    click.echo(EXAMPLE_YAML)

@cli.command()
def themes():
    """List available themes."""
    for name in THEMES:
        t = THEMES[name]
        click.echo(f"  {name:25s}  bg={t['bg']}  fg={t['fg']}")

if __name__ == "__main__":
    cli()
