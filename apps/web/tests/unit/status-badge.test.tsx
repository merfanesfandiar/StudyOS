/**
 * Status badges must be legible, and that is a property of the theme values
 * rather than of the component.
 *
 * Three statuses shipped with `bg-[var(--color-positive)] text-[var(--color-positive)]`
 * and its two siblings: the text was painted in the same colour as its own
 * background, so the label was invisible. Reviewing the class strings is how
 * that gets missed, because the string looks deliberate -- it names a colour
 * twice, symmetrically, and nothing about reading it says the two are the same
 * colour.
 *
 * So this test does not look at class strings. It reads the real palette out of
 * `globals.css`, resolves each badge's background and text token to actual sRGB
 * in both themes, and asserts WCAG contrast. Changing a token in the stylesheet,
 * or pairing two tokens wrongly in the component, fails here instead of in front
 * of a user.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { STATUS_STYLES } from "@/components/ui";
import type { AssignmentStatus } from "@/lib/types";

type Rgb = [number, number, number];
type Oklch = [number, number, number];

const AA_NORMAL_TEXT = 4.5;

function palettes(): Record<"light" | "dark", Record<string, Oklch>> {
  const css = readFileSync(join(process.cwd(), "app/globals.css"), "utf8");
  const grab = (from: string, to: string) => {
    const block = css.slice(css.indexOf(from), css.indexOf(to, css.indexOf(from)));
    const tokens: Record<string, Oklch> = {};
    for (const [, name, l, c, h] of block.matchAll(
      /--color-([\w-]+):\s*oklch\(([\d.]+)%?\s+([\d.]+)\s+([\d.]+)\)/g,
    )) {
      tokens[name] = [Number(l), Number(c), Number(h)];
    }
    return tokens;
  };
  return {
    light: grab("@theme {", ":root {"),
    dark: grab(':root[data-theme="dark"] {', "/* Follow the OS"),
  };
}

/** oklch to gamma-encoded sRGB, matching what the browser actually paints. */
function toRgb([lightness, C, H]: Oklch): Rgb {
  // oklch lightness is authored as a percentage (`oklch(95% ...)`); the
  // conversion wants 0-1.
  const L = lightness / 100;
  const h = (H * Math.PI) / 180;
  const a = C * Math.cos(h);
  const b = C * Math.sin(h);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const encode = (c: number) => {
    const v = Math.max(0, Math.min(1, c));
    // 0.0031308 is where the sRGB transfer function switches to its linear
    // segment. Using the 0.04045 value that WCAG uses for *decoding* here would
    // bend the dark end of every colour and quietly shift every ratio.
    return v <= 0.0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - 0.055;
  };
  return [
    encode(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    encode(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    encode(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

function luminance([r, g, b]: Rgb): number {
  const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(fg: Oklch, bg: Oklch): number {
  const a = luminance(toRgb(fg));
  const b = luminance(toRgb(bg));
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

const themes = palettes();

/** The `--color-*` name a Tailwind arbitrary-value class refers to. */
function tokenOf(classes: string, property: "bg" | "text"): string {
  const match = classes.match(new RegExp(`${property}-\\[var\\(--color-([\\w-]+)\\)\\]`));
  if (!match) throw new Error(`no ${property} colour token in: ${classes}`);
  return match[1];
}

const statuses = Object.keys(STATUS_STYLES) as AssignmentStatus[];

describe("status badge legibility", () => {
  it("covers every assignment status", () => {
    expect(statuses.length).toBe(8);
  });

  for (const status of statuses) {
    for (const theme of ["light", "dark"] as const) {
      it(`${status} text clears AA on its background in ${theme}`, () => {
        const classes = STATUS_STYLES[status];
        const bg = themes[theme][tokenOf(classes, "bg")];
        const fg = themes[theme][tokenOf(classes, "text")];
        expect(bg, `${theme} background token missing from globals.css`).toBeDefined();
        expect(fg, `${theme} text token missing from globals.css`).toBeDefined();
        expect(contrast(fg!, bg!)).toBeGreaterThanOrEqual(AA_NORMAL_TEXT);
      });
    }
  }

  it("never paints text in the colour it sits on", () => {
    // The specific failure: a saturated tone used as both background and text.
    // Checked separately from the contrast check because it is the mistake worth
    // naming, and because a future theme could make some same-token pair
    // legible by accident.
    for (const status of statuses) {
      const classes = STATUS_STYLES[status];
      expect(tokenOf(classes, "bg"), `${status} hides its own label`).not.toBe(
        tokenOf(classes, "text"),
      );
    }
  });

  it("does not ring the badge in the same colour as its text", () => {
    // A ring sharing the text colour reads as a second, competing edge and was
    // part of why the pill looked like one solid block.
    for (const status of statuses) {
      expect(STATUS_STYLES[status]).not.toMatch(/ring-/);
    }
  });
});