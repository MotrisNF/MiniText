"""Geometry and rendering for every centered overlay box drawn on top
of the editor - the "Close Mini" button and its welcome banner, the
new-file/new-folder name dialog, and the y/n confirm box (with its own
optional scrollable file list) - split out of rendering.py, which
still calls into these from its own `render()` and passes the results
through `self._mouse_layout` for `mouse.py`'s hit-testing to use."""

import theme
from rendering import _CLOSE_HOVER_COLOR

# The welcome screen's own banner - shown above the "Close Mini"
# button on the blank/unnamed/unmodified last-tab screen, mouse
# enabled or not. A hand-built block-letter wordmark spelling
# "MiniText", not derived from Banner.txt (mechanically downscaling
# that wider prototype - the previous approach - shrank it down to an
# unreadable blob; see bugs_conocidos.md). Banner.txt itself is kept
# untouched as the original prototype, just no longer the render's own
# source. Capitals (M, T) stand the full 5 rows tall; lowercase
# letters only occupy the bottom 3 (a plain x-height/baseline split,
# "i"'s dot sitting in the 2 rows above it) - each pixel is drawn as 2
# characters wide for a bolder, more legible look at normal terminal
# font sizes.
_BANNER_LINES = (
    "██      ██  ██          ██  ██████████                        ",
    "████  ████                      ██                        ██  ",
    "██  ██  ██  ██  ██████  ██      ██      ██████  ██  ██  ██████",
    "██      ██  ██  ██  ██  ██      ██      ██████    ██      ██  ",
    "██      ██  ██  ██  ██  ██      ██      ██      ██  ██    ██  ",
)
_WELCOME_SUBTITLE = "Open a file to start"

# Longest a confirm dialog's own file list (see `_confirm_box_geometry`)
# ever shows at once before it scrolls instead - large enough that the
# common "handful of selected files" case never needs to scroll, small
# enough that the box doesn't dwarf the editor pane behind it even on
# a tall terminal.
_CONFIRM_MAX_VISIBLE_ITEMS = 8


class DialogMixin:

    @staticmethod
    def _code_area_bounds(
        editor_col_offset, gutter_width, content_width, file_settings
    ):
        """The horizontal span a centered overlay box (the "Close
        Mini" button, the New file/folder name dialog, ...) should be
        centered within - starting right after the gutter (line
        numbers/current-line marker), and no wider than the user's
        own chosen line-length limit (`file_settings["MAX_COLS"]`,
        see `theme.settings_for`) when that's turned on, so a box
        lines up with where a line of code itself is expected to end
        instead of stretching across whatever's left of a wide
        terminal (which, with the worktree panel open too, isn't even
        centered on the terminal itself)."""
        area_left = editor_col_offset + gutter_width
        area_width = content_width
        if file_settings["MAX_COLS_ENABLED"]:
            area_width = min(area_width, file_settings["MAX_COLS"])
        return area_left, max(1, area_width)

    @staticmethod
    def _centered_box_geometry(
        area_left, area_width, editor_rows, box_width, box_height
    ):
        """The on-screen rectangle a `box_width`x`box_height` overlay
        box, centered within `_code_area_bounds`'s own span, lands at
        this frame - shared by every centered overlay box (`render`'s
        own `_close_mini_box_geometry` and the new-file/new-folder
        name dialog) so there's exactly one place computing the
        geometry `_mouse_target`'s hit-testing must always agree with
        what actually got drawn. None when the box can't fit at all
        (a terminal or editor pane too narrow/short for it), rather
        than drawing something clipped or unclickable."""
        if box_width > area_width or editor_rows < box_height:
            return None
        left = area_left + (area_width - box_width) // 2
        top_row_offset = max(0, (editor_rows - box_height) // 2)
        return {
            "left": left, "top_row_offset": top_row_offset,
            "width": box_width, "height": box_height,
            "row_offset_start": top_row_offset,
            "row_offset_end": top_row_offset + box_height - 1,
            "col_start": left, "col_end": left + box_width - 1,
        }

    def _close_mini_box_geometry(self, area_left, area_width, editor_rows):
        label = "Close Mini"
        box_width = len(label) + 4
        box = self._centered_box_geometry(
            area_left, area_width, editor_rows, box_width, 3
        )
        if box is not None:
            box["label"] = label
        return box

    def _render_close_mini_box(self, box):
        left, width, label = box["left"], box["width"], box["label"]
        top_row = 2 + box["top_row_offset"]
        color = (
            theme.CURRENT_LINE_INDICATOR_COLOR if self._hovered_close_mini
            else theme.SUGGESTION_COLOR
        )
        top_border = "┌" + "─" * (width - 2) + "┐"
        label_row = "│" + label.center(width - 2) + "│"
        bottom_border = "└" + "─" * (width - 2) + "┘"
        return [
            f"\x1b[{top_row};{left + 1}H{color}{top_border}"
            f"{theme.BASE_STYLE}",
            f"\x1b[{top_row + 1};{left + 1}H{color}{label_row}"
            f"{theme.BASE_STYLE}",
            f"\x1b[{top_row + 2};{left + 1}H{color}{bottom_border}"
            f"{theme.BASE_STYLE}",
        ]

    def _welcome_banner_geometry(self, close_box, area_left, area_width):
        """Where the banner + subtitle land, directly above the
        "Close Mini" button (`close_box`) they're anchored to - always
        computed relative to it so the whole block (banner, subtitle,
        button) reads as one centered unit rather than two separately
        placed things. None if there isn't enough width for the wider
        of the two, or enough height above the button to fit both -
        the button alone still shows either way, exactly as before
        this existed."""
        block_width = max(
            max(len(line) for line in _BANNER_LINES), len(_WELCOME_SUBTITLE)
        )
        if block_width > area_width:
            return None
        banner_rows = len(_BANNER_LINES)
        # banner, one blank row, the subtitle, one blank row, then
        # close_box's own top border right below.
        top_row_offset = close_box["top_row_offset"] - banner_rows - 2
        if top_row_offset < 0:
            return None
        return {
            "left": area_left + (area_width - block_width) // 2,
            "width": block_width,
            "banner_top_row_offset": top_row_offset,
            "subtitle_row_offset": top_row_offset + banner_rows + 1,
        }

    def _render_welcome_banner(self, banner):
        left, width = banner["left"], banner["width"]
        color = theme.SUGGESTION_COLOR
        output = []
        for offset, line in enumerate(_BANNER_LINES):
            row = 2 + banner["banner_top_row_offset"] + offset
            output.append(
                f"\x1b[{row};{left + 1}H{color}{line.center(width)}"
                f"{theme.BASE_STYLE}"
            )
        subtitle_row = 2 + banner["subtitle_row_offset"]
        output.append(
            f"\x1b[{subtitle_row};{left + 1}H{color}"
            f"{_WELCOME_SUBTITLE.center(width)}{theme.BASE_STYLE}"
        )
        return output

    def _name_dialog_box_geometry(
        self, area_left, area_width, editor_rows, label
    ):
        """Where the "new file/folder name" dialog (see worktree.py's
        `_prompt_name_dialog`) lands this frame - same centered-box
        machinery as `_close_mini_box_geometry`, just one row taller
        for its own input line below the label. `close_col` is the
        0-indexed display column of the "×" drawn into the top
        border's own top-right corner (see `_render_name_dialog_box`)
        - None with the mouse off, since there's nothing to click it
        with and `Esc` already cancels the dialog just fine."""
        box_width = max(len(label) + 4, 26)
        box = self._centered_box_geometry(
            area_left, area_width, editor_rows, box_width, 4
        )
        if box is None:
            return None
        box["label"] = label
        box["close_col"] = (
            box["col_end"] - 1 if theme.MOUSE_ENABLED else None
        )
        return box

    def _render_name_dialog_box(self, box, dialog):
        left, width = box["left"], box["width"]
        top_row = 2 + box["top_row_offset"]
        color = theme.SUGGESTION_COLOR
        if box["close_col"] is None:
            top_border = "┌" + "─" * (width - 2) + "┐"
        else:
            close_color = (
                _CLOSE_HOVER_COLOR if dialog.get("close_hovered") else color
            )
            # Bold, so the single "×" character doesn't get lost in a
            # border made of the same box-drawing weight - explicitly
            # un-bolded (\x1b[22m) right after, since theme.py's own
            # escape codes never issue a true SGR reset (\x1b[0m),
            # only reassign fg/bg colors, so a left-open bold would
            # otherwise bleed into every render after this one.
            top_border = (
                "┌" + "─" * (width - 3)
                + f"\x1b[1m{close_color}×\x1b[22m{color}" + "┐"
            )
        label_row = "│" + box["label"].center(width - 2) + "│"
        inner_width = width - 4
        value = dialog["value"]
        visible_value = (
            value[-inner_width:] if len(value) > inner_width else value
        )
        input_row = "│ " + visible_value.ljust(inner_width) + " │"
        bottom_border = "└" + "─" * (width - 2) + "┘"
        return [
            f"\x1b[{top_row};{left + 1}H{color}{top_border}"
            f"{theme.BASE_STYLE}",
            f"\x1b[{top_row + 1};{left + 1}H{color}{label_row}"
            f"{theme.BASE_STYLE}",
            f"\x1b[{top_row + 2};{left + 1}H{color}{input_row}"
            f"{theme.BASE_STYLE}",
            f"\x1b[{top_row + 3};{left + 1}H{color}{bottom_border}"
            f"{theme.BASE_STYLE}",
        ]

    def _confirm_box_geometry(
        self, area_left, area_width, editor_rows, prompt, items=None,
        scroll=0,
    ):
        """Where a y/n confirmation (see commands.py's `_confirm`)
        lands this frame, mouse mode only - same centered-box
        machinery as `_close_mini_box_geometry`/
        `_name_dialog_box_geometry`, one row taller than "Close Mini"
        for its own Yes/No buttons row. `yes_col_start`/`yes_col_end`
        and `no_col_start`/`no_col_end` are each button's own 0-indexed
        display-column span within that row, for hit-testing and
        hover, the same idea as `_name_dialog_box_geometry`'s single
        `close_col`.

        Unlike the name dialog, `prompt` here isn't bounded by
        anything Mini controls (it can list several dragged/deleted
        file names) - `box_width` is clamped to `area_width` rather
        than requiring the box to fully fit it, so a long prompt
        truncates (`_render_confirm_box` already does this for its own
        text) instead of silently drawing no box at all while
        `_confirm` keeps blocking on `y`/`n`/`Esc` with nothing on
        screen to show for it. Only genuinely too-narrow buttons
        (`area_width` itself smaller than the Yes/No row) still return
        None outright - nothing sensible to clamp to at that point.

        `items`, when given (more than one file moved/deleted at
        once - see worktree.py's `_worktree_delete`/
        `_handle_worktree_drop`), is shown as its own scrollable list
        between the prompt and the buttons instead of being folded
        into `prompt` itself as a comma-joined string - that was the
        old approach, and it just truncated once the names didn't fit
        on one line (see bugs_conocidos.md). At most
        `_CONFIRM_MAX_VISIBLE_ITEMS` rows show at once, further
        clamped down to whatever `editor_rows` actually leaves room
        for; `scroll` (persisted on `_confirm`'s own
        `self._confirm_dialog`, the only thing that survives between
        one frame and the next while the dialog is up) picks which
        window of `items` that is, and is clamped here right back into
        range in case the terminal got shorter since it was last
        changed. `has_more_above`/`has_more_below` record whether that
        window is hiding items off either end, for `_render_confirm_
        box` to draw a "there's more" arrow for."""
        yes_text, gap, no_text = "[ Yes ]", "   ", "[ No ]"
        buttons_text = yes_text + gap + no_text
        min_width = len(buttons_text) + 4
        content_lengths = [len(prompt)]
        if items:
            content_lengths.extend(len(item) for item in items)
        box_width = min(
            max(max(content_lengths) + 4, min_width, 24),
            max(area_width, min_width),
        )
        non_list_rows = 4  # top border, prompt, buttons, bottom border
        if items:
            visible_rows = min(len(items), _CONFIRM_MAX_VISIBLE_ITEMS)
            available_for_list = editor_rows - non_list_rows
            if available_for_list < visible_rows:
                visible_rows = max(1, available_for_list)
        else:
            visible_rows = 0
        box_height = non_list_rows + visible_rows
        box = self._centered_box_geometry(
            area_left, area_width, editor_rows, box_width, box_height
        )
        if box is None:
            return None
        box["prompt"] = prompt
        box["items"] = items or []
        box["visible_rows"] = visible_rows
        if items:
            max_scroll = max(0, len(items) - visible_rows)
            scroll = max(0, min(scroll, max_scroll))
        else:
            scroll = 0
        box["scroll"] = scroll
        box["has_more_above"] = bool(items) and scroll > 0
        box["has_more_below"] = (
            bool(items) and scroll + visible_rows < len(items)
        )
        inner_width = box["width"] - 2
        left_pad = (inner_width - len(buttons_text)) // 2
        # +1: box["left"] is the column of the border itself ("│"),
        # the first inner column is one past it.
        buttons_left0 = box["left"] + 1 + left_pad
        box["yes_col_start"] = buttons_left0
        box["yes_col_end"] = buttons_left0 + len(yes_text) - 1
        box["no_col_start"] = box["yes_col_end"] + len(gap) + 1
        box["no_col_end"] = box["no_col_start"] + len(no_text) - 1
        box["buttons_row_offset"] = (
            box["top_row_offset"] + 2 + visible_rows
        )
        return box

    def _render_confirm_list_rows(self, box, list_top_row):
        """The scrollable file-list rows between `_render_confirm_
        box`'s own prompt and buttons rows - one row per currently
        visible item (`box["scroll"]`..`+box["visible_rows"]`, both
        set by `_confirm_box_geometry`), each truncated with an
        ellipsis rather than wrapped, the same "one line per entry,
        clipped if it doesn't fit" treatment `_render_name_dialog_box`
        already gives its own single input line. The last column of
        each row is reserved for a "▲"/"▼" scroll arrow (a combined
        "↕" when a single visible row is hiding items on both ends -
        only possible on a very short terminal, but still needs to
        pick one glyph over the other) rather than spending a whole
        extra row on it, so the list itself doesn't shrink just to
        make room for its own scroll hint."""
        left, width = box["left"], box["width"]
        color = theme.SUGGESTION_COLOR
        items, scroll = box["items"], box["scroll"]
        visible_rows = box["visible_rows"]
        content_width = width - 2 - 2
        lines = []
        for offset in range(visible_rows):
            item_index = scroll + offset
            name = items[item_index] if item_index < len(items) else ""
            if len(name) > content_width:
                name = name[:max(0, content_width - 1)] + "…"
            is_first, is_last = offset == 0, offset == visible_rows - 1
            top_arrow = is_first and box["has_more_above"]
            bottom_arrow = is_last and box["has_more_below"]
            if top_arrow and bottom_arrow:
                indicator = "↕"
            elif top_arrow:
                indicator = "▲"
            elif bottom_arrow:
                indicator = "▼"
            else:
                indicator = " "
            row_text = "│ " + name.ljust(content_width) + indicator + "│"
            row = list_top_row + offset
            lines.append(
                f"\x1b[{row};{left + 1}H{color}{row_text}"
                f"{theme.BASE_STYLE}"
            )
        return lines

    def _render_confirm_box(self, box, dialog):
        left, width = box["left"], box["width"]
        top_row = 2 + box["top_row_offset"]
        color = theme.SUGGESTION_COLOR
        top_border = "┌" + "─" * (width - 2) + "┐"
        prompt_row = "│" + box["prompt"][:width - 2].center(width - 2) + "│"
        yes_text, gap, no_text = "[ Yes ]", "   ", "[ No ]"
        buttons_text = yes_text + gap + no_text
        inner_width = width - 2
        left_pad = (inner_width - len(buttons_text)) // 2
        right_pad = inner_width - len(buttons_text) - left_pad
        yes_color = (
            theme.CURRENT_LINE_INDICATOR_COLOR
            if dialog.get("hovered") == "yes" else color
        )
        no_color = (
            theme.CURRENT_LINE_INDICATOR_COLOR
            if dialog.get("hovered") == "no" else color
        )
        buttons_inner = (
            " " * left_pad
            + f"\x1b[1m{yes_color}{yes_text}\x1b[22m{color}"
            + gap
            + f"\x1b[1m{no_color}{no_text}\x1b[22m{color}"
            + " " * right_pad
        )
        buttons_row = f"│{buttons_inner}│"
        bottom_border = "└" + "─" * (width - 2) + "┘"
        visible_rows = box.get("visible_rows", 0)
        buttons_row_index = top_row + 2 + visible_rows
        lines = [
            f"\x1b[{top_row};{left + 1}H{color}{top_border}"
            f"{theme.BASE_STYLE}",
            f"\x1b[{top_row + 1};{left + 1}H{color}{prompt_row}"
            f"{theme.BASE_STYLE}",
        ]
        if visible_rows:
            lines.extend(
                self._render_confirm_list_rows(box, top_row + 2)
            )
        lines.append(
            f"\x1b[{buttons_row_index};{left + 1}H{color}{buttons_row}"
            f"{theme.BASE_STYLE}"
        )
        lines.append(
            f"\x1b[{buttons_row_index + 1};{left + 1}H{color}"
            f"{bottom_border}{theme.BASE_STYLE}"
        )
        return lines
