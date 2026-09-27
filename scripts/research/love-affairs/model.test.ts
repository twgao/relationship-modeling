import { describe, expect, it } from 'vitest'
import { CASES, RequestBudget, advanceResearch, continuousControl, focalContext, heldObservationUpdate, makeContext, seededRandom, validateObservations } from './model'
import type { JevResult } from '../../../src/lib/simulation/jev-interaction'

function fixture() {
  const context = makeContext(CASES[0])
  const [r, j] = context.participants
  const affection = { [r.characterId]: 0.2, [j.characterId]: 0 }
  const coefficients = { [r.characterId]: { a: 0, b: 1 }, [j.characterId]: { a: 0, b: -1 } }
  const observations = [
    { listenerId: r.characterId, speakerId: j.characterId, value: -0.4, evidenceLineId: 'line-2', quote: 'I need some space.' },
    { listenerId: j.characterId, speakerId: r.characterId, value: 0.6, evidenceLineId: 'line-1', quote: 'I like being here with you.' },
  ]
  // This accepted native result is a unit-test fixture, never a claimed provider result.
  const result = { success: true, effects: [], decision: {}, interaction: { type: 'small_talk', summary: 'Romeo expresses affection; Juliet asks for space.', exchanges: [{ speaker: r.name, speech: observations[1]!.quote }, { speaker: j.name, speech: observations[0]!.quote }], relationshipUpdates: [{ characterId: r.characterId, targetCharacterId: j.characterId, delta: 1 }] } } as unknown as JevResult
  return { context, r, j, affection, coefficients, observations, result }
}

describe('exact held observation model', () => {
  it('handles zero self-term, signed feedback, zero cross-term, and clipping', () => {
    expect(heldObservationUpdate(0.2, 0.6, { a: 0, b: -1 }, 0.5).value).toBeCloseTo(-0.1)
    expect(heldObservationUpdate(0.2, 0.6, { a: -1, b: 0 }, 0.5).value).toBeCloseTo(0.2 * Math.exp(-0.5))
    expect(heldObservationUpdate(0.2, -0.4, { a: 1, b: 2 }, 0.5).value).toBeCloseTo(0.2 * Math.exp(0.5) - 0.8 * Math.expm1(0.5))
    const clipped = heldObservationUpdate(0.9, 1, { a: 1, b: 2 }, 0.5)
    expect(clipped.value).toBe(1); expect(clipped.boundHit).toBe(true); expect(clipped.unclipped).toBeGreaterThan(1)
  })
  it('recovers continuous period, and explicitly detects held-oracle radius growth', () => {
    for (const spec of CASES) {
      const point = continuousControl(spec.id, [0.2, 0], 2 * Math.PI)
      expect(point[0]).toBeCloseTo(0.2); expect(point[1]).toBeCloseTo(0)
    }
    const next = [heldObservationUpdate(0.2, 0, { a: 0, b: 1 }, 0.5).value, heldObservationUpdate(0, 0.2, { a: 0, b: -1 }, 0.5).value]
    expect(Math.hypot(...next) / 0.2).toBeCloseTo(Math.sqrt(1.25))
    let sg = [0.2, 0]
    for (let index = 0; index < 5; index++) { const prior = sg; sg = CASES[1].coefficients.map((c, i) => heldObservationUpdate(prior[i]!, prior[1 - i]!, c, 0.5).value) }
    expect(sg[0]).toBeCloseTo(0.27555603); expect(sg[1]).toBeCloseTo(-0.40154803)
    expect(continuousControl('susan-george', [0.2, 0], 2.5).every(n => n < 0)).toBe(true)
  })
})

describe('directionality and atomic acceptance', () => {
  it('remaps focal order without changing coefficient owner or counterpart evidence', () => {
    const f = fixture()
    const original = advanceResearch(f.context, f.affection, f.coefficients, f.result, f.observations, 0.5)
    const reversed = advanceResearch(focalContext(f.context, f.j.characterId), f.affection, f.coefficients, f.result, f.observations, 0.5)
    expect(original.affection).toEqual(reversed.affection)
    expect(original.affection[f.r.characterId]).toBeCloseTo(0)
    expect(original.affection[f.j.characterId]).toBeCloseTo(-0.3)
    expect(reversed.context.participants[0].characterId).toBe(f.j.characterId)
  })
  it('rejects own speech, fabricated quote, duplicate listener and out-of-range values', () => {
    const f = fixture(); if (!f.result.success) throw new Error('fixture')
    for (const patch of [{ speakerId: f.r.characterId }, { quote: 'invented' }, { value: 2 }, { evidenceLineId: 'line-1' }]) {
      expect(validateObservations([{ ...f.observations[0], ...patch }, f.observations[1]], f.context, f.result.interaction.exchanges)).toBeNull()
    }
    expect(validateObservations([f.observations[0], f.observations[0]], f.context, f.result.interaction.exchanges)).toBeNull()
  })
  it('keeps every native and research state unchanged after either rejection', () => {
    const f = fixture(); const snapshot = JSON.stringify(f.context)
    for (const result of [f.result, { success: false, stage: 'appraisal', reason: 'invalid_appraisal' } as JevResult]) {
      const next = advanceResearch(f.context, f.affection, f.coefficients, result, [], 0.5)
      expect(next.accepted).toBe(false); expect(next.context).toBe(f.context); expect(next.affection).toBe(f.affection)
    }
    expect(JSON.stringify(f.context)).toBe(snapshot)
  })
  it('preserves directed knownFacts after native relationship reducers and adds spoken memory', () => {
    const f = fixture()
    const next = advanceResearch(f.context, f.affection, f.coefficients, f.result, f.observations, 0.5)
    expect(next.context.participants[0].relationships[0]!.knownFacts).toEqual(f.r.relationships[0]!.knownFacts)
    expect(next.context.participants[0].memories[0]!.content).toContain('Juliet said: "I need some space."')
    expect(f.context.participants[0].memories).toHaveLength(0)
  })
})

describe('request accounting and reaction seeds', () => {
  it('reserves before dispatch, never refunds failed calls, and refuses more requests', () => {
    const budget = new RequestBudget(3, 0.3, 0.1)
    expect(budget.canReserveEncounter()).toBe(true)
    expect(budget.reserve()).toBe(1)
    expect(budget.canReserveEncounter()).toBe(false)
    budget.reserve(); budget.reserve()
    expect(() => budget.reserve()).toThrow('Budget exhausted')
    expect(budget.calls).toBe(3)
    const money = new RequestBudget(60, 0.1, 0.1); money.reserve()
    expect(() => money.reserve()).toThrow('Budget exhausted')
  })
  it('replays categorical draws within [0,1) with distinct seeded streams', () => {
    const a = seededRandom(12), b = seededRandom(12), c = seededRandom(13)
    const values = Array.from({ length: 20 }, () => a())
    expect(values).toEqual(Array.from({ length: 20 }, () => b()))
    expect(values).not.toEqual(Array.from({ length: 20 }, () => c()))
    expect(values.every(n => n >= 0 && n < 1)).toBe(true)
  })
})
