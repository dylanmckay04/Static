/**
 * Deterministic SVG sigil seal generator.
 * Same sigil string always produces the same SVG.
 */

// ── Seeded LCG RNG ────────────────────────────────────────────────────────

function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = (h * 16777619) >>> 0
  }
  return h
}

function makePrng(seed: number) {
  let s = seed >>> 0
  return () => {
    s = (Math.imul(1664525, s) + 1013904223) >>> 0
    return s / 0xffffffff
  }
}

// ── Glyph alphabet ────────────────────────────────────────────────────────
// 20 rune-like paths, all defined in a 0-20 local coordinate space.
// Each glyph is an array of SVG path `d` strings.

const GLYPHS: string[] = [
  'M10,2 L10,18 M6,7 L14,7',                             // Isa + cross
  'M6,2 L10,18 L14,2',                                   // Tiwaz (arrow up)
  'M6,18 L10,2 L14,18',                                  // Tiwaz (arrow down)
  'M6,6 L10,2 L14,6 M6,14 L10,18 L14,14',               // double chevron
  'M10,2 L10,18 M6,2 L14,2 M6,18 L14,18',               // I-beam
  'M6,2 L14,10 L6,18',                                   // Laguz
  'M14,2 L6,10 L14,18',                                  // Laguz mirrored
  'M6,2 L14,2 L10,10 L14,18 L6,18',                     // Odal-like
  'M10,2 L14,10 L10,18 L6,10 Z',                        // diamond
  'M6,2 L10,10 L14,2 M6,18 L10,10 L14,18',              // Gebo (X)
  'M10,2 L10,18 M6,10 L14,10 M7,5 L13,5',               // Nauthiz
  'M6,2 L6,18 L14,10 L6,10',                            // Raidho
  'M14,2 L14,18 L6,10 L14,10',                          // Raidho mirrored
  'M6,14 L6,6 L14,6 L14,14',                            // open square
  'M6,2 L14,2 L14,18 M6,10 L14,10',                     // Berkano-like
  'M6,6 L10,2 L14,6 L10,18',                            // Dagaz-like
  'M10,2 C4,6 4,14 10,18 C16,14 16,6 10,2',            // eye/oval
  'M6,2 L14,18 M14,2 L6,18 M10,2 L10,18',              // triple cross
  'M10,2 L10,18 M6,6 L14,6 M6,14 L14,14',              // double bar
  'M6,10 L10,2 L14,10 M6,10 L10,18 L14,10',            // hexagonal diamond
]

// ── Shape outlines ─────────────────────────────────────────────────────────
// Defined as SVG path `d` strings in a 0-60 coordinate space (cx=30, cy=30, r=26)

type Shape = { outline: string; cx: number; cy: number; r: number }

const SHAPES: Shape[] = [
  // circle
  {
    outline: 'M30,4 A26,26 0 1,1 29.99,4 Z',
    cx: 30, cy: 30, r: 18,
  },
  // triangle (equilateral, pointing up)
  {
    outline: 'M30,4 L54,48 L6,48 Z',
    cx: 30, cy: 32, r: 15,
  },
  // pentagon
  {
    outline: (() => {
      const pts = Array.from({ length: 5 }, (_, i) => {
        const a = (i * 72 - 90) * (Math.PI / 180)
        return `${30 + 26 * Math.cos(a)},${30 + 26 * Math.sin(a)}`
      })
      return 'M' + pts.join(' L') + ' Z'
    })(),
    cx: 30, cy: 30, r: 16,
  },
  // hexagon
  {
    outline: (() => {
      const pts = Array.from({ length: 6 }, (_, i) => {
        const a = (i * 60 - 90) * (Math.PI / 180)
        return `${30 + 26 * Math.cos(a)},${30 + 26 * Math.sin(a)}`
      })
      return 'M' + pts.join(' L') + ' Z'
    })(),
    cx: 30, cy: 30, r: 17,
  },
]

// ── Accent ring positions ──────────────────────────────────────────────────
// Small dots placed on the perimeter of the shape

function perimeterDots(shape: Shape, count: number): Array<{ x: number; y: number }> {
  return Array.from({ length: count }, (_, i) => {
    const a = (i / count) * Math.PI * 2 - Math.PI / 2
    return {
      x: shape.cx + (shape.r + 6) * Math.cos(a),
      y: shape.cy + (shape.r + 6) * Math.sin(a),
    }
  })
}

// ── Main export ────────────────────────────────────────────────────────────

export function generateSigilSvg(sigil: string, size = 48): string {
  const seed = hash(sigil)
  const rng  = makePrng(seed)

  const shape    = SHAPES[Math.floor(rng() * SHAPES.length)]
  const dotCount = 3 + Math.floor(rng() * 4)          // 3–6 perimeter dots
  const dots     = perimeterDots(shape, dotCount)

  // Pick 2–3 glyphs; place them inside the shape
  const glyphCount = 1 + Math.floor(rng() * 2)         // 1–2 glyphs
  const chosenGlyphs = Array.from({ length: glyphCount }, () =>
    GLYPHS[Math.floor(rng() * GLYPHS.length)]
  )

  // Each glyph gets a position offset + small rotation
  const glyphElements = chosenGlyphs.map((d, i) => {
    const ox  = shape.cx - 10 + (rng() - 0.5) * (shape.r * 0.5) * (glyphCount > 1 ? 1 : 0)
    const oy  = shape.cy - 10 + (rng() - 0.5) * (shape.r * 0.4) * (glyphCount > 1 ? 1 : 0)
    const rot = (rng() - 0.5) * 30
    const sc  = 0.55 + rng() * 0.3
    // offset second glyph so they don't perfectly overlap
    const dx  = glyphCount > 1 ? (i === 0 ? -5 : 5) : 0
    return `<g transform="translate(${ox + dx},${oy}) rotate(${rot.toFixed(1)},10,10) scale(${sc.toFixed(2)})">
      <path d="${d}" stroke="currentColor" stroke-width="1.5" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
    </g>`
  }).join('\n')

  const dotElements = dots.map(({ x, y }) =>
    `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="1.4" fill="currentColor" opacity="0.7"/>`
  ).join('\n')

  // Accent color picked from gold palette
  const colors = ['#c9a227', '#b8891a', '#d4af37', '#a07d18', '#c9943a']
  const color  = colors[Math.floor(rng() * colors.length)]

  return `<svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 60 60"
    width="${size}"
    height="${size}"
    aria-label="${sigil} seal"
    style="color:${color}; flex-shrink:0;"
  >
    <path d="${shape.outline}" stroke="currentColor" stroke-width="1.2" fill="none" opacity="0.75"/>
    ${dotElements}
    ${glyphElements}
  </svg>`
}

/** React-safe: returns the SVG as a string for dangerouslySetInnerHTML */
export function sigilSvgHtml(sigil: string, size = 36): string {
  return generateSigilSvg(sigil, size)
}
