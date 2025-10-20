#!/usr/bin/env python3
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style


DATA_FILE = Path(__file__).with_name("nerdicons_data.json")


@lru_cache(maxsize=1)
def load_nerdicons() -> list[str]:
    try:
        raw = json.loads(DATA_FILE.read_text())
    except FileNotFoundError:
        return []

    items: list[str] = []
    for name, hex_value in raw.items():
        try:
            code_point = int(hex_value, 16)
            glyph = chr(code_point)
        except ValueError:
            continue
        items.append(f"{glyph} {name} (U+{hex_value.upper()})")
    return items

DEFAULT_STYLE = Style.from_dict({
    "prompt": "ansicyan bold",
    "input": "ansicyan",
    "panel-border": "ansibrightblack",
    "panel-line": "",
    "panel-placeholder": "ansibrightblack",
    "selected-line": "reverse",
    "footer": "ansibrightblack",
    "no-results": "italic ansiyellow",
})


class _PanelPromptSession:
    def __init__(
        self,
        prompt_text: str,
        choices: Optional[Iterable[str]] = None,
        style: Optional[Style] = None,
        max_rows: int = 6,
    ) -> None:
        self.prompt_text = prompt_text
        self.choices = list(choices) if choices is not None else []
        self.style = style or DEFAULT_STYLE
        self.max_rows = max_rows

        self.panel_width = 80
        self.panel_inner_width = self.panel_width - 4

        self.input_text = ""
        self.filtered_items: list[str] = []
        self.selected_index = 0
        self.view_start = 0

        self.filter_items()

    def filter_items(self) -> None:
        source = self.choices
        previous_value: Optional[str] = None
        if self.filtered_items and 0 <= self.selected_index < len(self.filtered_items):
            previous_value = self.filtered_items[self.selected_index]

        query = self.input_text.strip()
        if not query:
            filtered = list(source)
        else:
            lowered = query.lower()
            filtered = [item for item in source if lowered in item.lower()]

        sorted_items = self._sort_items(filtered, query)
        self.filtered_items = sorted_items

        if not sorted_items:
            self.selected_index = 0
            self.view_start = 0
            return
        if previous_value and previous_value in sorted_items:
            self.selected_index = sorted_items.index(previous_value)
        else:
            self.selected_index = 0

        self._ensure_selection_visible(reset_view=previous_value not in sorted_items)

    def _sort_items(self, items: list[str], query: str) -> list[str]:
        if not items:
            return []

        if not query:
            return sorted(items)

        lowered = query.lower()

        def sort_key(item: str) -> tuple[int, int, str]:
            text = item.lower()
            starts_with = 0 if text.startswith(lowered) else 1
            position = text.find(lowered)
            position = position if position >= 0 else len(text)
            return (starts_with, position, text)

        return sorted(items, key=sort_key)

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        if width <= 0:
            return ""
        if len(text) <= width:
            return text
        if width == 1:
            return "…"
        return text[: width - 1] + "…"

    def _panel_header(self, title: str) -> FormattedText:
        inner = f" {title} "
        line_len = self.panel_width - 2
        header = inner.center(line_len, "─")
        return [("class:panel-border", f"┌{header}┐\n")]

    def _panel_footer(self) -> FormattedText:
        line_len = self.panel_width - 2
        return [("class:panel-border", f"└{'─' * line_len}┘\n")]

    def _panel_row(self, text: str, style: str) -> FormattedText:
        padded = text.ljust(self.panel_inner_width)
        return [
            ("class:panel-border", "│ "),
            (style, padded),
            ("class:panel-border", " │\n"),
        ]

    def render_panel(self) -> FormattedText:
        lines: FormattedText = []

        if not self.filtered_items:
            lines.extend(self._panel_header("No results"))
            message = self._truncate("Tidak ada hasil", self.panel_inner_width)
            lines.extend(self._panel_row(message, "class:no-results"))

            for _ in range(self.max_rows - 1):
                lines.extend(self._panel_row("", "class:panel-placeholder"))
        else:
            lines.extend(self._panel_header("NerdIcons"))
            for idx in range(self.max_rows):
                actual_index = self.view_start + idx
                if actual_index < len(self.filtered_items):
                    item = self.filtered_items[actual_index]
                    is_selected = actual_index == self.selected_index
                    prefix = "› " if is_selected else "  "
                    formatted = self._format_item_columns(
                        item, self.panel_inner_width - len(prefix)
                    )
                    content = prefix + formatted
                    style = "class:selected-line" if is_selected else "class:panel-line"
                else:
                    content = ""
                    style = "class:panel-placeholder"

                lines.extend(self._panel_row(content, style))

        lines.extend(self._panel_footer())
        return lines

    def render_content(self) -> FormattedText:
        parts: FormattedText = []
        parts.append(("class:prompt", self.prompt_text))
        parts.append(("class:input", self.input_text))

        if self.filtered_items:
            parts.append(("", "\n\n"))
            parts.extend(self.render_panel())
            parts.append(("", "\n"))

        parts.append(("class:footer", "Tab: isi dari pilihan | Ctrl+C: batal"))
        return parts

    def _accept_selection(self) -> None:
        if self.filtered_items:
            self.input_text = self.filtered_items[self.selected_index]

    def _ensure_selection_visible(self, reset_view: bool = False) -> None:
        if not self.filtered_items:
            self.view_start = 0
            return

        if self.max_rows <= 0:
            self.view_start = 0
            return

        max_view_start = max(len(self.filtered_items) - self.max_rows, 0)

        if reset_view:
            self.view_start = max(0, min(self.selected_index, max_view_start))
            return

        if self.selected_index < self.view_start:
            self.view_start = self.selected_index
        elif self.selected_index >= self.view_start + self.max_rows:
            self.view_start = self.selected_index - self.max_rows + 1

        self.view_start = max(0, min(self.view_start, max_view_start))

    def _format_item_columns(self, item: str, content_width: int) -> str:
        if content_width <= 0:
            return ""

        try:
            glyph, rest = item.split(" ", 1)
            name, code = rest.rsplit(" ", 1)
        except ValueError:
            return self._truncate(item, content_width)

        separator = " · "
        separators_len = len(separator) * 2
        base_len = len(glyph) + len(code) + separators_len

        if content_width <= base_len + 1:
            return self._truncate(item, content_width)

        name_space = content_width - base_len
        name_text = self._truncate(name, name_space)
        if len(name_text) < name_space:
            name_text = name_text.ljust(name_space)

        return f"{glyph}{separator}{name_text}{separator}{code}"

    def run(self) -> str:
        kb = KeyBindings()

        @kb.add("up")
        def _(event) -> None:
            if self.filtered_items and self.selected_index > 0:
                self.selected_index -= 1
                self._ensure_selection_visible()

        @kb.add("down")
        def _(event) -> None:
            if self.filtered_items and self.selected_index < len(self.filtered_items) - 1:
                self.selected_index += 1
                self._ensure_selection_visible()

        @kb.add("tab")
        def _(event) -> None:
            if self.filtered_items:
                self._accept_selection()
                self.filter_items()
                self._ensure_selection_visible()

        @kb.add("enter")
        def _(event) -> None:
            text = self.input_text
            if not text and self.filtered_items:
                text = self.filtered_items[self.selected_index]
            event.app.exit(result=text)

        @kb.add("escape")
        def _(event) -> None:
            self.input_text = ""
            self.filter_items()

        @kb.add("backspace")
        def _(event) -> None:
            if self.input_text:
                self.input_text = self.input_text[:-1]
                self.filter_items()

        @kb.add("c-u")
        def _(event) -> None:
            self.input_text = ""
            self.filter_items()

        @kb.add("c-c")
        def _(event) -> None:
            event.app.exit(exception=KeyboardInterrupt)

        for char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_ ":
            @kb.add(char)
            def _(event, c=char) -> None:
                self.input_text += c
                self.filter_items()

        layout = Layout(
            Window(
                content=FormattedTextControl(self.render_content),
                always_hide_cursor=True,
            )
        )

        app = Application(
            layout=layout,
            key_bindings=kb,
            full_screen=False,
            mouse_support=False,
            erase_when_done=True,
            style=self.style,
        )

        return app.run()


def complete_panel_prompt(
    prompt_text: str = "❯ ",
    choices: Optional[Iterable[str]] = None,
    *,
    style: Optional[Style] = None,
    max_rows: int = 10,
) -> str:
    prompt = _PanelPromptSession(
        prompt_text,
        choices or load_nerdicons(),
        style,
        max_rows=max_rows,
    )
    return prompt.run()


class PanelInput:
    def __init__(
        self,
        *,
        choices: Optional[Iterable[str]] = None,
        style: Optional[Style] = None,
        max_rows: int = 6,
    ) -> None:
        self._choices = list(choices) if choices is not None else load_nerdicons()
        self._style = style or DEFAULT_STYLE
        self._max_rows = max_rows

    @property
    def choices(self) -> list[str]:
        return self._choices

    @choices.setter
    def choices(self, value: Iterable[str]) -> None:
        self._choices = list(value)

    @property
    def style(self) -> Style:
        return self._style

    @style.setter
    def style(self, value: Style) -> None:
        self._style = value

    def prompt(self, prompt_text: str = "❯ ") -> str:
        session = _PanelPromptSession(
            prompt_text,
            self._choices,
            self._style,
            max_rows=self._max_rows,
        )
        return session.run()

    __call__ = prompt


if __name__ == "__main__":
    try:
        while True:
            value = complete_panel_prompt()
            print(value)
    except (EOFError, KeyboardInterrupt):
        print()
