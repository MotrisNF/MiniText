# Deferred: multi-line-aware comment/docstring highlighting

Scope: make syntax highlighting correctly recognize a `"""`/`'''`
docstring (Python) or a `/* */` comment (C/C++) that spans more than
one line, instead of only recognizing one that starts and ends on the
same line. Currently documented as a known limitation in
[README.md](README.md#limitations). Deferred to its own session -
this is a real architecture change to `highlighting.py`, comparable in
size to the `rendering.py`/`autocomplete.py` splits already done, not
a small tweak - see "Why this is bigger than it looks" below.

## Current state (why the limitation exists)

`highlighting.py`'s own module docstring says it plainly:
`_highlight_python`/`_highlight_c` color "one line's tokens... 
independently - no awareness of multi-line constructs". Concretely:

- `_highlight_python(display_text, lookahead="")` (`highlighting.py`)
  is a single `_TOKEN_PATTERN.sub(_colorize, display_text)` call with
  no memory of anything before `display_text` other than the
  optional `lookahead` (a few characters of *look-ahead*, not
  look-behind, and not from a previous line either - see
  `_is_function_call`'s own docstring).
- `is_in_triple_quoted_string(line, column)` (`highlighting.py:35`)
  scans `line` alone with `TRIPLE_QUOTE_PATTERN.finditer(line)` - a
  `"""` that opened on an *earlier* line is invisible to it. Its own
  docstring already says so: "same single-line-only reach as
  everything else here".
- `_is_inside_string_or_comment`/`_is_inside_c_string_or_comment`
  (autocomplete.py / c_autocomplete.py) have the identical limitation,
  used to suppress autocomplete suggestions inside a string/comment -
  a multi-line docstring/comment would need the same fix in both
  places to stay consistent (no suggestions popping up inside a
  docstring that started on a previous line).
- `rendering.py`'s own `_render_segment` (line ~339) calls
  `apply_highlight` **more than once per line** in two cases: once per
  sub-range when a word-match highlight splits the line into pieces,
  and once each side of the bracket-match column when the cursor sits
  on a bracket - each call sees only its own fragment of the line's
  text, with no shared state even *within* that one line's own
  rendering.

## Why this is bigger than it looks

Detecting "is this line already inside an unclosed comment/docstring"
needs to know about *every earlier line in the file*, not just the
current one. Making that fast enough to not lag on every keystroke
needs an incremental cache, not a full rescan from line 0 on every
render:

1. **A new per-buffer cache**: something like `self._comment_state`,
   one entry per line - "what construct (if any) was still open
   *entering* this line" (`None` / `"python-triple-double"` /
   `"python-triple-single"` / `"c-block-comment"`). Computing line
   N's own exit state needs line N's entry state plus its own text -
   naturally incremental, one line depends on the one before it.
2. **Invalidation on every edit**: inserting/deleting text can flip
   whether a docstring/comment is open from that point on - so every
   line *after* the edited one needs its cached state recomputed, up
   until a line whose own state happens to resync regardless (or to
   the end of the file). This needs hooking into every place
   `self.lines` actually changes in `editing.py` (insert, backspace,
   delete, paste, new line, undo/redo) - more entangled call sites
   than the `_word_pool_line_index`/`_worktree_entries_cache`
   invalidation patterns already in the codebase, since those only
   care about "did the line count or cursor line change", not
   "recompute a chain of per-line values from a specific point
   onward".
3. **Threading the state through rendering**: `_render()`'s own row
   loop needs to pass each line's entry state into `_render_segment`/
   `_render_wrapped_segment`, which need to pass it into
   `apply_highlight` - and get back not just colored text but an exit
   state too. The bracket-match/word-match splitting in
   `_render_segment` (see above) needs restructuring so the
   comment-state computation happens once, over the *whole* line,
   separate from however many pieces the line gets chopped into for
   display - otherwise a word-match highlight inside a docstring would
   lose track of "we're inside a docstring" for that one fragment.
4. **`is_in_triple_quoted_string`/`_is_inside_string_or_comment`/
   `_is_inside_c_string_or_comment`** all need the same per-line entry
   state passed in (not just `line`/`column`), since bracket/quote
   matching and autocomplete both call these and would otherwise stay
   just as single-line-blind as before, even after highlighting itself
   is fixed.
5. **Edge cases to design for explicitly**: a docstring/comment left
   unclosed for the rest of the file (a typo, or a file still being
   written); what a soft-wrapped line's own multiple screen rows do
   with a state change partway through (today each wrapped segment
   already gets its own `apply_highlight` call - see
   `_render_wrapped_segment`); and interaction with undo/redo (an undo
   that reopens/closes a multi-line construct needs the cache to catch
   up too, not just forward edits).

## Suggested approach, when picked up

1. Design the cache and its invalidation first, in isolation, with its
   own tests (given a list of lines and an edit range, what needs
   recomputing) - before touching any rendering code at all.
2. Extend `_highlight_python`/`_highlight_c` to accept an entry state
   and return an exit state alongside the colored text, keeping the
   plain single-line call signature working for anything that doesn't
   care about the state yet (autocomplete's own single-position checks
   could adopt this second, once the cache exists).
3. Restructure `_render_segment`'s bracket/word-match splitting to
   compute the line's own coloring once, over the whole line, then
   slice the *already-colored* pieces apart for the bracket-match/
   word-match treatment - rather than calling `apply_highlight` once
   per piece as it does now.
4. Wire the cache into `_render()`'s row loop last, once the above two
   are independently correct and tested.
5. Do Python's `"""`/`'''` first, then C/C++'s `/* */` as a second,
   separate pass reusing the same cache mechanism (different states,
   same invalidation machinery) - the user's own preference, if this
   gets picked up in stages rather than all at once.
