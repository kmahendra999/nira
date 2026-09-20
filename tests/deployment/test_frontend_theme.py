"""The design tokens must actually reach the markup.

Until Phase 8 there was no ``@theme`` block, so ``bg-surface`` and
``text-text-secondary`` were not classes and there was no way to write a colour
in markup at all. The codebase worked around that with 975 ``style={{ }}``
objects and 68 handlers assigning to ``e.currentTarget.style``. An inline style
cannot express ``:hover``, ``:focus-visible`` or ``:active``, so every
interaction state was simulated in JavaScript — and simulated hover reaches
neither the keyboard nor a touchscreen.

Checked from pytest rather than vitest because it is a fact about a file, not
about runtime behaviour: vitest stubs CSS imports to the empty string, and
reading the file with ``node:fs`` would need Node types this browser tsconfig
does not have. Adding them means an npm install, which is what silently
rewrote ``package-lock.json`` once already.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

INDEX_CSS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "index.css"


def _css() -> str:
    return INDEX_CSS.read_text(encoding="utf-8")


def _theme_keys(css: str) -> list[str]:
    match = re.search(r"@theme inline \{(.*?)\n\}", css, re.S)
    assert match, "index.css has no @theme inline block"
    return re.findall(r"^\s*(--[a-z0-9-]+):", match.group(1), re.M)


def _tokens_in(css: str, selector: str) -> list[str]:
    match = re.search(rf"{re.escape(selector)} \{{(.*?)\n  \}}", css, re.S)
    assert match, f"index.css has no {selector} block"
    return re.findall(r"^\s*(--[a-z0-9-]+):", match.group(1), re.M)


class TestThemeTokens:
    def test_the_palette_is_exposed_as_utilities(self) -> None:
        keys = _theme_keys(_css())

        assert "--color-surface" in keys
        assert "--color-accent" in keys
        assert "--color-text-secondary" in keys
        assert len(keys) > 30

    def test_every_theme_key_is_backed_by_a_root_token(self) -> None:
        css = _css()
        root = _tokens_in(css, ":root")

        # ``@theme inline`` emits ``--x: var(--x)``, which is only meaningful
        # because :root defines --x for real, later in the cascade. A key with
        # no backing token is circular, resolves to nothing, and its utility
        # silently does nothing — which reads as a styling mistake rather than
        # a missing token.
        unbacked = [key for key in _theme_keys(css) if key not in root]
        assert unbacked == [], f"@theme keys with no :root token: {unbacked}"

    def test_the_dark_palette_is_a_subset_of_the_light_one(self) -> None:
        css = _css()
        root = _tokens_in(css, ":root")
        dark = _tokens_in(css, ".dark")

        # A token defined only in .dark is invisible in light mode, and a name
        # that drifted between the two blocks keeps its light value in dark
        # mode. Both read as "this one element did not get themed".
        assert dark, "the dark palette is empty"
        orphans = [token for token in dark if token not in root]
        assert orphans == [], f"defined in .dark but not :root: {orphans}"

    def test_every_themed_colour_has_a_dark_value(self) -> None:
        css = _css()
        dark = _tokens_in(css, ".dark")

        missing = [
            key
            for key in _theme_keys(css)
            if key.startswith("--color-") and key not in dark
        ]
        assert missing == [], f"themed colours with no dark value: {missing}"

    def test_keyboard_focus_is_visible(self) -> None:
        css = _css()

        # There was no :focus-visible rule anywhere in the frontend, so tabbing
        # through the app moved an invisible cursor.
        assert ":focus-visible {" in css, "no global focus ring"
        focus = re.search(r"\n  :focus-visible \{(.*?)\n  \}", css, re.S)
        assert focus, "the focus ring is not a bare :focus-visible rule"
        assert "outline" in focus.group(1)

    def test_the_focus_ring_is_not_keyed_to_mouse_focus(self) -> None:
        css = _css()

        # A bare `:focus` ring fires on every mouse click too, which is the
        # reason people delete focus rings in the first place.
        stray = re.findall(r"^\s*[^@/\n]*[^-]:focus \{", css, re.M)
        assert stray == [], f"plain :focus rules: {stray}"


@pytest.mark.parametrize(
    "utility",
    ["bg-surface", "text-text-secondary", "bg-bg-tertiary", "border-border"],
)
def test_converted_markup_uses_real_utilities(utility: str) -> None:
    """The utilities the conversion relies on must resolve to a token.

    A typo like ``bg-surfce`` is not an error in Tailwind — it produces no CSS
    at all, and the element silently keeps whatever it inherited.
    """
    css = _css()
    keys = _theme_keys(css)
    # Strip the utility prefix to recover the token namespace.
    suffix = utility.split("-", 1)[1]
    assert f"--color-{suffix}" in keys, f"{utility} has no --color-{suffix} token"


SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _tsx_files() -> list[Path]:
    return sorted(SRC.rglob("*.tsx"))


def _open_tags(text: str, tag: str):
    """Yield ``(line, attributes)`` for each opening ``<tag …>``.

    Arrow functions are neutralised first. A naive ``[^<>]*`` stops dead at the
    ``>`` of ``=>``, so an attribute list containing a handler is truncated
    before the interesting part — which made this check quietly pass over
    exactly the elements it exists to find.
    """
    masked = text.replace("=>", "=\u0000")
    for match in re.finditer(rf"<{tag}\b((?:[^<>]|\n)*?)>", masked):
        attrs = match.group(1).replace("=\u0000", "=>")
        yield text[: match.start()].count("\n") + 1, attrs


class TestInteractionStatesAreCss:
    """Hover, focus and press belong in CSS, not in event handlers.

    Assigning to ``e.currentTarget.style`` was the only way to express a hover
    state before the tokens became utilities, and it has three failure modes
    that are invisible to whoever writes it: a keyboard user gets no state at
    all, a touch user gets one that sticks after the tap because nothing ever
    fires ``mouseleave``, and the handler silently wins over any stylesheet
    rule for the same property. Tailwind's ``hover:`` is wrapped in
    ``@media (hover: hover)``, so it simply does not apply on a touchscreen.
    """

    def test_no_component_assigns_to_current_target_style(self) -> None:
        offenders = {
            path.relative_to(SRC).as_posix(): path.read_text(encoding="utf-8").count(
                "currentTarget.style"
            )
            for path in _tsx_files()
            if "currentTarget.style" in path.read_text(encoding="utf-8")
        }
        assert offenders == {}, (
            "interaction state simulated in JavaScript: "
            f"{offenders}. Use hover:/focus-visible:/active: utilities."
        )

    def test_no_component_fakes_press_state_with_mouse_events(self) -> None:
        # onMouseDown/onMouseUp to scale a button never fires for a keyboard
        # activation, so the control feels dead to anyone pressing Enter.
        offenders = [
            path.relative_to(SRC).as_posix()
            for path in _tsx_files()
            if "onMouseDown" in (text := path.read_text(encoding="utf-8"))
            and "transform" in text
            and "currentTarget" in text
        ]
        assert offenders == [], f"press state faked with mouse events: {offenders}"


class TestKeyboardReachability:
    def test_no_click_handler_on_a_plain_div(self) -> None:
        """A div with onClick and no role cannot be reached or activated.

        It takes no focus, does not respond to Enter, and is announced as
        nothing — the control is simply absent for anyone not using a mouse.

        Two shapes are not controls and are allowed. A container whose handler
        only calls ``stopPropagation`` is plumbing, not something to press. A
        backdrop that dismisses on click is scenery: it must carry
        ``aria-hidden`` so it is not announced, and ``Escape`` has to do the
        same job — which is what :meth:`test_a_dismissable_overlay_answers_to_escape`
        checks.
        """
        offenders = []
        for path in _tsx_files():
            text = path.read_text(encoding="utf-8")
            for line, attrs in _open_tags(text, "div"):
                if "onClick" not in attrs:
                    continue
                if "role=" in attrs and "tabIndex" in attrs:
                    continue
                if "stopPropagation" in attrs and "=>" in attrs:
                    # Swallows a bubbling click; nothing to activate.
                    continue
                if "fixed inset-0" in attrs:
                    continue
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{line}")
        assert offenders == [], (
            "clickable <div> without role and tabIndex: "
            f"{offenders}. Use a <button>, or add role/tabIndex/onKeyDown."
        )

    def test_a_dismissable_overlay_answers_to_escape(self) -> None:
        """An overlay you can only click away is a trap for the keyboard.

        Backdrop dismissal is exempt from the rule above precisely because
        Escape is meant to do the same job. If it does not, the exemption is
        hiding a dead end rather than describing a pattern.
        """
        offenders = []
        for path in _tsx_files():
            text = path.read_text(encoding="utf-8")
            dismissable = any(
                "fixed inset-0" in attrs and "onClick" in attrs
                for _line, attrs in _open_tags(text, "div")
            )
            if dismissable and "Escape" not in text:
                offenders.append(path.relative_to(SRC).as_posix())
        assert offenders == [], (
            f"overlay dismissable only by mouse: {offenders}. Handle Escape."
        )


class TestFocusIsNeverSuppressed:
    """`outline-none` beats the global ring, because utilities win the cascade.

    The base `:focus-visible` rule is in `@layer base`; a Tailwind utility is
    in `@layer utilities`, which is declared later and therefore wins at equal
    specificity. So every `outline-none` silently reinstates the problem the
    ring exists to solve — and on a form field, which is where it matters most.
    """

    def test_outline_is_only_suppressed_where_a_container_shows_focus(
        self,
    ) -> None:
        offenders = []
        for path in _tsx_files():
            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if "outline-none" not in line:
                    continue
                # The one legitimate shape: a transparent, borderless field
                # inside a styled box, where the box shows focus instead.
                if "bg-transparent" in line and "focus-within" in text:
                    continue
                offenders.append(f"{path.relative_to(SRC).as_posix()}:{line_no}")
        assert offenders == [], (
            "focus ring suppressed with no replacement: "
            f"{offenders}. Drop outline-none, or give the container "
            "focus-within styling."
        )


def _relative_luminance(hex_colour: str) -> float:
    """WCAG relative luminance for an opaque #rrggbb colour."""
    raw = hex_colour.lstrip("#")
    channels = [int(raw[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [
        c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _palette(selector: str) -> dict[str, str]:
    """Opaque hex tokens declared in one palette block."""
    css = _css()
    match = re.search(rf"{re.escape(selector)} \{{(.*?)\n  \}}", css, re.S)
    assert match, f"no {selector} block"
    return dict(
        re.findall(r"^\s*(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6});", match.group(1), re.M)
    )


class TestTextContrast:
    """Muted text has to be readable, not merely present.

    ``--color-text-tertiary`` carries timestamps, hints and field descriptions
    — the small text that most needs to be legible — and sat at 2.43:1 on a
    near-white page against the 4.5:1 WCAG AA asks for. Checked by computing
    the ratio rather than by pinning the hex values, so a later recolour cannot
    quietly drop back under the line.
    """

    # Every surface muted text is drawn on, per palette.
    BACKGROUNDS = (
        "--color-bg",
        "--color-surface",
        "--color-bg-secondary",
        "--color-bg-tertiary",
    )
    FOREGROUNDS = ("--color-text", "--color-text-secondary", "--color-text-tertiary")

    @pytest.mark.parametrize("selector", [":root", ".dark"])
    def test_text_clears_wcag_aa_on_every_surface(self, selector: str) -> None:
        palette = _palette(selector)
        failures = []
        for fg in self.FOREGROUNDS:
            if fg not in palette:
                continue
            for bg in self.BACKGROUNDS:
                # Some surfaces are rgba() and are skipped by _palette; the
                # opaque ones are the ones text actually sits on.
                if bg not in palette:
                    continue
                ratio = _contrast(palette[fg], palette[bg])
                if ratio < 4.5:
                    failures.append(f"{fg} on {bg} = {ratio:.2f}:1")
        assert failures == [], f"{selector} below WCAG AA (4.5:1): {failures}"

    @pytest.mark.parametrize("selector", [":root", ".dark"])
    def test_the_three_text_levels_stay_distinguishable(self, selector: str) -> None:
        # Fixing contrast by making every level the same colour would pass the
        # check above and destroy the hierarchy it exists to serve.
        palette = _palette(selector)
        bg = palette["--color-bg"]
        ratios = [
            _contrast(palette[name], bg) for name in self.FOREGROUNDS if name in palette
        ]
        assert ratios == sorted(ratios, reverse=True), (
            f"{selector}: text levels are not ordered by contrast: {ratios}"
        )
        assert len(set(round(r, 1) for r in ratios)) == len(ratios), (
            f"{selector}: two text levels are visually identical: {ratios}"
        )


class TestTabsAreAnnouncedAsTabs:
    """A tab rendered as a bare button is announced as a bare button.

    Nothing says the buttons form a group, nothing says which one is showing,
    and every one of them sits in the tab order — so reaching the panel means
    pressing Tab once per tab first.
    """

    def test_a_tab_strip_uses_the_tablist_roles(self) -> None:
        orphans = []
        for path in _tsx_files():
            text = path.read_text(encoding="utf-8")
            if 'role="tablist"' not in text:
                continue
            missing = [
                needed
                for needed in ('role="tab"', "aria-selected", "aria-controls")
                # tabProps() supplies these; a file using the helper is fine.
                if needed not in text and "tabProps" not in text
            ]
            if missing:
                orphans.append(f"{path.relative_to(SRC).as_posix()}: {missing}")
        assert orphans == [], f"incomplete tablists: {orphans}"

    def test_the_roving_tabindex_keeps_its_focus_ring(self) -> None:
        css = _css()

        # Unselected tabs carry tabindex="-1" and *are* focused by the arrow
        # keys. A blanket [tabindex="-1"] suppression would hide the ring on
        # exactly the element the user just moved to.
        assert '[tabindex="-1"]:not([role]):focus-visible' in css, (
            "the tabindex=-1 focus suppression must exclude elements with a "
            "role, or roving-tabindex tabs lose their focus ring"
        )
