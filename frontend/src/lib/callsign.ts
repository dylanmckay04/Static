/**
 * Deterministic SVG callsign badge generator.
 * Same callsign string always produces the same SVG.
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
// 20 shortwave/signal-themed paths, all defined in a 0-20 local coordinate space.
// Each glyph is an array of SVG path `d` strings.

const GLYPHS: string[] = [
  'M10,18 L10,6 M6,6 L14,6 M10,6 L4,10 M10,6 L16,10',                                   // antenna tower
  'M2,10 C5,2 9,2 10,10 C11,18 15,18 18,10',                                             // sine wave
  'M2,13 L5,13 L5,6 L9,6 L9,13 L13,13 L13,6 L17,6 L17,13',                              // square wave
  'M3,18 L3,8 M7,18 L7,4 M11,18 L11,11 M15,18 L15,6',                                   // spectrum bars
  'M10,4 C17,4 17,16 10,16 M10,2 C20,2 20,18 10,18',                                    // radiating arcs
  'M10,2 L10,18 M2,10 L18,10 M10,10 m-4,0 a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0',            // crosshairs
  'M10,2 L18,16 L2,16 Z',                                                                 // triangle
  'M2,14 L8,4 L8,14 L14,4 L14,14',                                                       // sawtooth wave
  'M2,6 L18,6 M2,14 L18,14 M6,2 L6,18 M14,2 L14,18',                                   // grid
  'M2,10 L7,10 M9,8 L11,12 M9,12 L11,8 M13,10 L18,10',                                 // dash-X-dash
  'M10,18 L10,10 M7,8 A4,4 0 0,1 13,8 M5,5 A7,7 0 0,1 15,5 M3,2 A10,10 0 0,1 17,2',  // broadcast tower
  'M12,2 L6,10 L11,10 L8,18 L14,10 L9,10 Z',                                            // lightning bolt
  'M10,2 L18,10 L10,18 L2,10 Z',                                                         // diamond
  'M2,7 L18,7 M2,13 L18,13',                                                             // double bar
  'M4,4 L16,16 M4,16 L16,4 M2,10 L18,10',                                               // X with horizontal
  'M4,4 L16,4 L4,16 L16,16 Z',                                                           // hourglass
  'M2,10 L5,10 L5,4 L8,14 L11,4 L14,14 L17,4 L17,10',                                  // scope trace
  'M10,10 m-3,0 a3,3 0 1,0 6,0 a3,3 0 1,0 -6,0 M10,10 m-6,0 a6,6 0 1,0 12,0 a6,6 0 1,0 -12,0', // concentric rings
  'M10,10 L14,6 M6,10 A4,4 0 1,1 14,10',                                                // tuning dial
  'M2,10 L6,4 L6,16 L10,10 L14,4 L14,16 L18,10',                                       // chevron wave
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

export function generateCallsignSvg(callsign: string, size = 48): string {
  const seed = hash(callsign)
  const rng  = makePrng(seed)

  const shape    = SHAPES[Math.floor(rng() * SHAPES.length)]
  const dotCount = 3 + Math.floor(rng() * 4)          // 3–6 perimeter dots
  const dots     = perimeterDots(shape, dotCount)

  // Pick 1–2 glyphs; place them inside the shape
  const glyphCount = 1 + Math.floor(rng() * 2)
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

  // Accent color picked from amber palette
  const colors = ['#ffb000', '#cc8800', '#e6a000', '#ff9900', '#ffc333']
  const color  = colors[Math.floor(rng() * colors.length)]

  return `<svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 60 60"
    width="${size}"
    height="${size}"
    aria-label="${callsign}"
    style="color:${color}; flex-shrink:0;"
  >
    <path d="${shape.outline}" stroke="currentColor" stroke-width="1.2" fill="none" opacity="0.75"/>
    ${dotElements}
    ${glyphElements}
  </svg>`
}

/** React-safe: returns the SVG as a string for dangerouslySetInnerHTML */
export function callsignSvgHtml(callsign: string, size = 36): string {
  return generateCallsignSvg(callsign, size)
}
