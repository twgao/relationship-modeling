import type { InteractionPromptContext } from '../../../src/lib/simulation/interaction-prompt'
import type { JevResult } from '../../../src/lib/simulation/jev-interaction'
import { advanceAcceptedContext } from '../../../src/lib/simulation/evaluation/trajectories'

export type Affection = Record<string, number>
export interface Coefficients { a: number; b: number }
export interface Observation { listenerId: string; speakerId: string; value: number; evidenceLineId: string; quote: string }
export const CASES = [
  { id: 'romeo-juliet', names: ['Romeo', 'Juliet'], coefficients: [{ a: 0, b: 1 }, { a: 0, b: -1 }], personalities: ['Warm and expressive; speaks plainly about present feelings.', 'Independent and guarded; values personal space and uses understated speech.'] },
  { id: 'susan-george', names: ['Susan', 'George'], coefficients: [{ a: 1, b: 2 }, { a: -1, b: -1 }], personalities: ['Direct, earnest, and emotionally expressive; speaks with conviction.', 'Wry, hesitant, and prone to second thoughts; uses dry humor and cautious wording.'] },
] as const

export function heldObservationUpdate(r: number, u: number, { a, b }: Coefficients, h: number) {
  if (![r, u, a, b, h].every(Number.isFinite) || Math.abs(r) > 1 || Math.abs(u) > 1 || h < 0) throw new Error('Invalid update input')
  const phi = a === 0 ? h : Math.expm1(a * h) / a
  const unclipped = Math.exp(a * h) * r + b * phi * u
  if (!Number.isFinite(unclipped)) throw new Error('Nonfinite update')
  return { value: Math.max(-1, Math.min(1, unclipped)), unclipped, boundHit: Math.abs(unclipped) > 1 }
}

/** Both class matrices obey A²=-I; these controls observe the partner continuously. */
export function continuousControl(caseId: string, initial: readonly [number, number], t: number): [number, number] {
  const [x, y] = initial
  if (caseId === 'romeo-juliet') return [Math.cos(t) * x + Math.sin(t) * y, Math.cos(t) * y - Math.sin(t) * x]
  if (caseId === 'susan-george') return [Math.cos(t) * x + Math.sin(t) * (x + 2 * y), Math.cos(t) * y + Math.sin(t) * (-x - y)]
  throw new Error('Unknown control')
}

export function makeContext(spec: typeof CASES[number]): InteractionPromptContext {
  const people = spec.names.map((name, index) => ({
    characterId: `${spec.id}-${name.toLowerCase()}`, name, description: 'A fictional adult in an invented relationship scenario; no TV or literary events are established.',
    personality: spec.personalities[index], goals: [{ description: 'Have an honest present conversation about how being together feels, without assuming the other person’s feelings.' }],
    dreams: [], fears: [], mood: 'neutral', energy: 65, stress: 20, socialization: 50, memories: [], relationships: [],
  })) as unknown as [InteractionPromptContext['participants'][0], InteractionPromptContext['participants'][0]]
  people.forEach((person, index) => { person.relationships = [{ toCharacterId: people[1 - index]!.characterId, score: 0, relationshipType: 'acquaintance', description: 'A familiar adult companion. No prior conflict, promise, or reciprocal romantic feeling is established.', interactionCount: 1, knownFacts: ['Both are adult fictional characters; neither knows the other’s private feelings.'] }] })
  return { participants: people, characters: people.map(p => ({ id: p.characterId, name: p.name })), scene: { name: 'A quiet sitting room', description: 'Both adults are seated together for a conversation.' }, currentTick: 60, currentDay: 1, currentTimePeriod: 'morning', worldKnowledge: [], recentInteractions: [] }
}

export function focalContext(context: InteractionPromptContext, focalId: string): InteractionPromptContext {
  const actor = context.participants.find(p => p.characterId === focalId)
  const other = context.participants.find(p => p.characterId !== focalId)
  if (!actor || !other) throw new Error('Unknown focal actor')
  return { ...context, participants: [actor, other] }
}

export function validateObservations(raw: unknown, context: InteractionPromptContext, exchanges: readonly { speaker: string; speech: string }[]): Observation[] | null {
  if (!Array.isArray(raw) || raw.length !== 2) return null
  const rows: Observation[] = []
  for (const value of raw) {
    if (!value || typeof value !== 'object') return null
    const row = value as Observation
    const listener = context.participants.find(p => p.characterId === row.listenerId)
    const speaker = context.participants.find(p => p.characterId === row.speakerId)
    if (!listener || !speaker || listener === speaker || rows.some(r => r.listenerId === row.listenerId)) return null
    if (!Number.isFinite(row.value) || Math.abs(row.value) > 1 || typeof row.evidenceLineId !== 'string') return null
    const line = exchanges.find((_, i) => row.evidenceLineId === `line-${i + 1}`)
    if (!line || line.speaker !== speaker.name || typeof row.quote !== 'string' || row.quote !== line.speech) return null
    rows.push({ listenerId: row.listenerId, speakerId: row.speakerId, value: row.value, evidenceLineId: row.evidenceLineId, quote: row.quote })
  }
  return rows
}

/** A rejected native stage OR research observation leaves every state untouched. */
export function advanceResearch(context: InteractionPromptContext, affection: Affection, coefficients: Record<string, Coefficients>, result: JevResult, rawObservations: unknown, h: number) {
  const observations = result.success ? validateObservations(rawObservations, context, result.interaction.exchanges) : null
  if (!result.success || !observations) return { accepted: false as const, context, affection, updates: [] }
  const updates = observations.map(row => ({ characterId: row.listenerId, observation: row, ...heldObservationUpdate(affection[row.listenerId]!, row.value, coefficients[row.listenerId]!, h) }))
  const next = advanceAcceptedContext(context, result.interaction, result.effects)
  const participants = next.participants.map(person => {
    const previous = context.participants.find(p => p.characterId === person.characterId)!
    const observation = observations.find(row => row.listenerId === person.characterId)!
    const speakerName = context.participants.find(p => p.characterId === observation.speakerId)!.name
    return { ...person, relationships: person.relationships.map(relationship => ({ ...relationship, knownFacts: previous.relationships.find(r => r.toCharacterId === relationship.toCharacterId)?.knownFacts })),
      memories: [{ id: `spoken-${context.currentTick}-${person.characterId}`, content: `${speakerName} said: ${JSON.stringify(observation.quote)}. This records spoken words, not proof of private feelings.`, emotionalValence: 0, tick: context.currentTick }, ...person.memories].slice(0, 6) }
  }) as unknown as InteractionPromptContext['participants']
  return { accepted: true as const, context: { ...next, participants }, affection: Object.fromEntries(updates.map(row => [row.characterId, row.value])), updates }
}

/** Deterministic only for our categorical draw, never a provider language seed. */
export function seededRandom(seed: number) {
  let state = seed >>> 0
  return () => { state += 0x6D2B79F5; let n = state; n = Math.imul(n ^ n >>> 15, n | 1); n ^= n + Math.imul(n ^ n >>> 7, n | 61); return ((n ^ n >>> 14) >>> 0) / 4294967296 }
}

export class RequestBudget {
  calls = 0
  reservedUsd = 0
  constructor(readonly maxCalls: number, readonly maxUsd: number, readonly reservePerCallUsd: number) {
    if (!Number.isInteger(maxCalls) || maxCalls < 1 || maxCalls > 60 || ![maxUsd, reservePerCallUsd].every(n => Number.isFinite(n) && n > 0)) throw new Error('Invalid budget')
  }
  reserve(amount = this.reservePerCallUsd) {
    if (!Number.isFinite(amount) || amount <= 0) throw new Error('Invalid reservation')
    if (this.calls >= this.maxCalls || this.reservedUsd + amount > this.maxUsd + 1e-10) throw new Error('Budget exhausted')
    this.calls += 1
    this.reservedUsd += amount
    return this.calls
  }
  canReserveEncounter(amount = 3 * this.reservePerCallUsd) { return this.calls + 3 <= this.maxCalls && this.reservedUsd + amount <= this.maxUsd + 1e-10 }
}
