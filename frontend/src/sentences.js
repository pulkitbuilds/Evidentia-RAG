const ABBREVIATIONS = new Set([
  'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sr.', 'jr.', 'vs.', 'etc.',
  'e.g.', 'i.e.', 'fig.', 'no.', 'approx.', 'u.s.', 'u.k.', 'st.',
])

const BOUNDARY = /(?<=[.!?])\s+(?=[A-Z0-9"'\u201c])/

/**
 * Splits text into { text, complete } sentence objects.
 * The final sentence is marked incomplete if the text doesn't end with
 * whitespace after terminal punctuation (i.e. the user is still typing it).
 */
export function splitSentences(rawText) {
  const text = rawText.replace(/\s+/g, ' ').trim()
  if (!text) return []

  const pieces = text.split(BOUNDARY)
  const sentences = []
  let buffer = ''

  for (const piece of pieces) {
    const candidate = buffer ? `${buffer} ${piece}`.trim() : piece
    const lastWord = candidate.split(' ').pop().toLowerCase()
    if (ABBREVIATIONS.has(lastWord)) {
      buffer = candidate
      continue
    }
    sentences.push(candidate)
    buffer = ''
  }
  if (buffer) sentences.push(buffer)

  return sentences.map((s, i) => {
    const isLast = i === sentences.length - 1
    const complete = !isLast || /[.!?]$/.test(rawText.trim())
    return { text: s, complete }
  })
}
