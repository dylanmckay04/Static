/**
 * Occult sound engine — Web Audio API synthesis only, no files required.
 * All sounds are off by default; call setEnabled(true) to activate.
 */

let ctx: AudioContext | null = null
let enabled = false
let humGain: GainNode | null = null
let humOsc: OscillatorNode | null = null
let humLfo: OscillatorNode | null = null

function getCtx(): AudioContext {
  if (!ctx) ctx = new AudioContext()
  if (ctx.state === 'suspended') void ctx.resume()
  return ctx
}

// ── Candle hum loop ───────────────────────────────────────────────────────
// A very faint 55 Hz organ-like drone with a slow 0.3 Hz amplitude flutter

function startHum() {
  if (!enabled || humOsc) return
  const c = getCtx()

  humGain = c.createGain()
  humGain.gain.setValueAtTime(0, c.currentTime)
  humGain.gain.linearRampToValueAtTime(0.025, c.currentTime + 2)
  humGain.connect(c.destination)

  humOsc = c.createOscillator()
  humOsc.type = 'sine'
  humOsc.frequency.value = 55
  humOsc.connect(humGain)
  humOsc.start()

  // LFO for flutter
  humLfo = c.createOscillator()
  humLfo.type = 'sine'
  humLfo.frequency.value = 0.28
  const lfoGain = c.createGain()
  lfoGain.gain.value = 0.012
  humLfo.connect(lfoGain)
  lfoGain.connect(humGain.gain)
  humLfo.start()
}

function stopHum() {
  if (!humOsc || !humGain) return
  const c = getCtx()
  humGain.gain.linearRampToValueAtTime(0, c.currentTime + 1.5)
  const osc = humOsc; const lfo = humLfo
  setTimeout(() => { try { osc?.stop(); lfo?.stop() } catch {} }, 1600)
  humOsc = null; humLfo = null; humGain = null
}

// ── Incoming whisper tone ─────────────────────────────────────────────────
// Brief filtered noise burst — like a distant voice

export function playWhisperReceived() {
  if (!enabled) return
  const c = getCtx()

  const bufSize = c.sampleRate * 0.35
  const buf = c.createBuffer(1, bufSize, c.sampleRate)
  const data = buf.getChannelData(0)
  for (let i = 0; i < bufSize; i++) data[i] = Math.random() * 2 - 1

  const src = c.createBufferSource()
  src.buffer = buf

  const filter = c.createBiquadFilter()
  filter.type = 'bandpass'
  filter.frequency.value = 1800
  filter.Q.value = 2.5

  const gain = c.createGain()
  gain.gain.setValueAtTime(0.08, c.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + 0.35)

  src.connect(filter)
  filter.connect(gain)
  gain.connect(c.destination)
  src.start()
}

// ── Planchette / send click ───────────────────────────────────────────────
// Soft low thud

export function playMessageSent() {
  if (!enabled) return
  const c = getCtx()

  const osc = c.createOscillator()
  osc.type = 'sine'
  osc.frequency.setValueAtTime(160, c.currentTime)
  osc.frequency.exponentialRampToValueAtTime(60, c.currentTime + 0.12)

  const gain = c.createGain()
  gain.gain.setValueAtTime(0.18, c.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + 0.15)

  osc.connect(gain)
  gain.connect(c.destination)
  osc.start()
  osc.stop(c.currentTime + 0.16)
}

// ── Connection drop — descending omen ─────────────────────────────────────

export function playConnectionDrop() {
  if (!enabled) return
  const c = getCtx()

  const osc = c.createOscillator()
  osc.type = 'sawtooth'
  osc.frequency.setValueAtTime(320, c.currentTime)
  osc.frequency.exponentialRampToValueAtTime(80, c.currentTime + 0.7)

  const gain = c.createGain()
  gain.gain.setValueAtTime(0.07, c.currentTime)
  gain.gain.exponentialRampToValueAtTime(0.0001, c.currentTime + 0.7)

  const filter = c.createBiquadFilter()
  filter.type = 'lowpass'
  filter.frequency.value = 600

  osc.connect(filter)
  filter.connect(gain)
  gain.connect(c.destination)
  osc.start()
  osc.stop(c.currentTime + 0.75)
}

// ── Reconnected — ascending chime ─────────────────────────────────────────

export function playReconnected() {
  if (!enabled) return
  const c = getCtx()

  ;[220, 330, 440].forEach((freq, i) => {
    const osc = c.createOscillator()
    osc.type = 'sine'
    osc.frequency.value = freq

    const gain = c.createGain()
    const t = c.currentTime + i * 0.12
    gain.gain.setValueAtTime(0, t)
    gain.gain.linearRampToValueAtTime(0.07, t + 0.05)
    gain.gain.exponentialRampToValueAtTime(0.0001, t + 0.35)

    osc.connect(gain)
    gain.connect(c.destination)
    osc.start(t)
    osc.stop(t + 0.4)
  })
}

// ── Toggle ─────────────────────────────────────────────────────────────────

export function setEnabled(on: boolean) {
  enabled = on
  if (on) startHum()
  else    stopHum()
}

export function isEnabled() { return enabled }
