import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createHash } from 'node:crypto'
import { CASES, RequestBudget, advanceResearch, continuousControl, focalContext, heldObservationUpdate, makeContext, seededRandom, type Affection } from './model'
import type { JevStatusEvent } from '../../../src/lib/simulation/jev-interaction'
import { JEV_MODEL_ID } from '../../../src/lib/simulation/jev-decision'
import { INTERACTION_COMPLETION_SETTINGS } from '../../../src/lib/simulation/interaction-prompt'
import { TWO_PASS_MODEL_ID, TWO_PASS_SETTINGS } from '../../../src/lib/simulation/two-pass-interaction'
import { createEvaluationTransport } from '../../../src/lib/simulation/evaluation/bedrock-transport'
import { finalTextOnly } from '../../../src/lib/simulation/evaluation/harness'
import { reserveEvaluationBudget } from '../../../src/lib/simulation/evaluation/budget-ledger'

function argument(name: string, fallback?: string) {
  const index = process.argv.indexOf(name)
  return index < 0 ? fallback : process.argv[index + 1]
}
function parseCompletion(text: string): Record<string, unknown> | null {
  try { return JSON.parse(text.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')) as Record<string, unknown> } catch { return null }
}
function safeJevPayload(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeJevPayload)
  if (typeof value === 'string') return finalTextOnly(value)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value).filter(([key]) => !/reasoning|thinking|scratchpad|chain.?of.?thought|authorization|api.?key|secret|credential/i.test(key)).map(([key, entry]) => [key, safeJevPayload(entry)]))
}

async function main() {
  const live = process.argv.includes('--live')
  if (live && process.env.STORY_PROVIDER_ENV_FILE) {
    const loaded = JSON.parse(readFileSync(process.env.STORY_PROVIDER_ENV_FILE, 'utf8')) as Record<string, unknown>
    if (!loaded || Object.keys(loaded).some(key => key !== 'TYPESAFE_API_KEY') || typeof loaded.TYPESAFE_API_KEY !== 'string' || !loaded.TYPESAFE_API_KEY.trim()) throw new Error('Invalid restricted provider credential file')
    process.env.TYPESAFE_API_KEY = loaded.TYPESAFE_API_KEY
  }
  const { runJevInteraction } = await import('../../../src/lib/simulation/jev-interaction')
  const steps = Number(argument('--steps', '5'))
  const maxCalls = Number(argument('--max-calls', '60'))
  const maxUsd = Number(argument('--max-usd', '2'))
  const reservations = { rating: 0.002774016, dialogue: 0.0596608, appraisal: 0.00658432 }
  const encounterReservation = reservations.rating + reservations.dialogue + reservations.appraisal
  if (!Number.isInteger(steps) || steps < 1 || steps > 5) throw new Error('Steps must be 1..5')
  const budget = new RequestBudget(maxCalls, maxUsd, reservations.dialogue)
  if (maxUsd > 2 || 4 * steps * 3 > maxCalls || 4 * steps * encounterReservation > maxUsd + 1e-10) throw new Error('Complete balanced pilot exceeds declared request/reservation bounds')
  const h = 0.5
  const seeds = [20260927, 20260928]
  const root = resolve(argument('--output', 'scratchpad/love-affairs-pilot-plan')!)
  const configuredModel = process.env.BEDROCK_MODEL_ID
  const sourcePaths = ['src/lib/simulation/jev-decision.ts', 'src/lib/simulation/jev-interaction.ts', 'src/lib/simulation/two-pass-interaction.ts', 'src/lib/simulation/social-policy.ts', 'src/lib/simulation/evaluation/trajectories.ts', 'src/lib/simulation/evaluation/bedrock-transport.ts', 'src/lib/simulation/evaluation/harness.ts', 'src/lib/simulation/evaluation/budget-ledger.ts', 'src/lib/simulation/interaction-prompt.ts', 'scripts/research/love-affairs/model.ts', 'scripts/research/love-affairs/run.ts']
  const manifest = {
    createdAt: new Date().toISOString(), mode: live ? 'live' : 'dry-plan', cases: CASES, seeds, stepsPerTrajectory: steps, trajectories: 4, maximumEncounters: 4 * steps, maximumProviderRequests: maxCalls,
    h, initialAffection: [0.2, 0], initialDeviation: 0, gaussianNoise: false, alternateFocalParticipant: true,
    models: { rating: JEV_MODEL_ID, dialogue: configuredModel ?? 'UNCONFIGURED: live requires BEDROCK_MODEL_ID', appraisal: TWO_PASS_MODEL_ID },
    settings: { dialogue: INTERACTION_COMPLETION_SETTINGS, appraisal: TWO_PASS_SETTINGS.appraisal, maxAttempts: 1 },
    budget: { maxUsd, reservationsByStageUsd: reservations, fullPlanReservationUsd: 4 * steps * encounterReservation, inputBounds: { bedrockPromptBytesPlus4096: 32768, jevPayloadBytes: 64000, jevFramingAllowance: 2048 },
      pricing: { checkedOn: '2026-09-27', awsRegionalPublication: '2026-09-26', usdPerMillionTokens: { jev: { input: 0.042, output: 0 }, kimi: { input: 0.60, output: 2.50 }, scout: { input: 0.17, output: 0.66 } }, sources: ['https://docs.typesafe.ai/models', 'https://aws.amazon.com/bedrock/pricing/', 'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json'] },
      meaning: 'Conservative per-request budget admission, NOT a provider-enforced billing ceiling. Jev has no maxTokens control and its output is listed as free at the checked rate. Reservations are not released after failures; usage is retained; invoice cost is unknown.' },
    design: 'Native Jev rates eight intentions; seeded categorical draw selects focal intent; configured joint writer produces both voices; native Scout appraisal plus separately validated utterance-grounded observations; pure native reducers and bounded affection update only after all checks pass.',
    limitations: ['Small descriptive pilot, not evidence of cycles or population proportions.', 'No guaranteed deterministic seed for provider language or ratings.', 'Research affection is distinct from native broad bond; no empirical calibration of warmth scale or response coefficients.', 'Warmth is an automated, uncalibrated expression rating. The native judge also sees selected intention and context, so this is not a blinded independent measure.', 'No full production memory/fact extraction, passive decay, scheduler, or DB persistence.', 'Appraisal never receives numerical private affection; warmth must be grounded in counterpart utterances. Joint writer does receive both states, as required by existing pipeline.', 'Held observations differ mathematically from continuously observed class equations; both continuous and held-oracle controls are saved.', 'Rejected encounters leave emotional/native state and model time unchanged; there are no retries.'],
    sourceHashes: Object.fromEntries(sourcePaths.map(path => [path, createHash('sha256').update(readFileSync(path)).digest('hex')])),
  }
  if (live && (!configuredModel || !process.env.TYPESAFE_API_KEY?.trim() || !process.env.AWS_ACCESS_KEY_ID || !process.env.AWS_SECRET_ACCESS_KEY)) throw new Error('Live requires explicit configured models and provider credentials')
  if (live && (configuredModel !== 'moonshot.kimi-k2-thinking' || (process.env.AWS_REGION || 'us-east-1') !== 'us-east-1' || TWO_PASS_MODEL_ID !== 'us.meta.llama4-scout-17b-instruct-v1:0' || JEV_MODEL_ID !== 'jev-1.13.0')) throw new Error('Configured model/region does not match the audited budget')
  mkdirSync(root, { recursive: false, mode: 0o700 })
  const secrets = Object.entries(process.env).filter(([key]) => /KEY|SECRET|TOKEN|PASSWORD/i.test(key)).map(([, value]) => value!).filter(value => value?.length >= 8)
  const save = (name: string, data: unknown) => {
    const text = JSON.stringify(data, null, 2) + '\n'
    if (secrets.some(secret => text.includes(secret))) throw new Error('Secret scan failed; artifact withheld')
    writeFileSync(resolve(root, name), text, { flag: 'wx', mode: 0o600 })
  }
  save('manifest.json', manifest)
  const controls = CASES.map(spec => {
    let held: [number, number] = [0.2, 0]
    let selfOnly: [number, number] = [0.2, 0]
    const points = Array.from({ length: steps + 1 }, (_, index) => {
      let heldUpdates: ReturnType<typeof heldObservationUpdate>[] = []
      if (index) { const prior = held; heldUpdates = spec.coefficients.map((c, i) => heldObservationUpdate(prior[i]!, prior[1 - i]!, c, h)); held = heldUpdates.map(row => row.value) as [number, number] }
      const selfOnlyUpdates = index ? spec.coefficients.map((c, i) => heldObservationUpdate(selfOnly[i]!, 0, { ...c, b: 0 }, h)) : []
      if (index) selfOnly = selfOnlyUpdates.map(row => row.value) as [number, number]
      return { step: index, t: index * h, continuousUnbounded: continuousControl(spec.id, [0.2, 0], index * h), heldOracleClipped: held, heldUpdates, selfOnlyClipped: selfOnly, selfOnlyUpdates }
    })
    return { caseId: spec.id, explanation: 'Planned full-step mechanical controls, with no generated dialogue. For a live row compare at acceptedStep, not attempt index: rejected attempts do not advance time. Held oracle replaces the utterance observation with the counterpart’s actual previous affection. This isolates sample-and-hold discretization from language effects. Self-only control sets b=0, retaining a, h, and clipping, to reveal self-amplification alone. Clipping remains enabled in both discrete controls.', points }
  })
  save('controls.json', controls)
  if (!live) { console.log(JSON.stringify({ mode: 'dry-plan', providerCalls: 0, output: root })); return }
  const manifestSha256 = createHash('sha256').update(JSON.stringify(manifest)).digest('hex')
  reserveEvaluationBudget(resolve(argument('--ledger', 'scratchpad/love-affairs-pilot-budget.json')!), { runId: root, manifestSha256, calls: 4 * steps * 3, reservedCostUsd: 4 * steps * encounterReservation }, { maxCalls, maxSpendUsd: maxUsd })
  const provider = createEvaluationTransport({ region: process.env.AWS_REGION || 'us-east-1' })
  const summary: Record<string, unknown>[] = []
  let stopped = false
  for (const spec of CASES) for (const seed of seeds) {
    let context = makeContext(spec)
    const ids = context.participants.map(p => p.characterId)
    let affection: Affection = Object.fromEntries(ids.map((id, i) => [id, i === 0 ? 0.2 : 0]))
    const coefficients = Object.fromEntries(ids.map((id, i) => [id, spec.coefficients[i]!]))
    const random = seededRandom(seed + (spec.id === 'susan-george' ? 1000 : 0))
    let acceptedSteps = 0
    for (let step = 0; step < steps; step++) {
      if (stopped || !budget.canReserveEncounter(encounterReservation)) { stopped = true; break }
      const prefix = `${spec.id}-${seed}-${String(step + 1).padStart(2, '0')}`
      const beforeAffection = { ...affection }
      const requestContext = focalContext(context, ids[step % 2]!)
      const status: JevStatusEvent[] = []
      let observations: unknown
      let completedCalls = 0
      const draws: number[] = []
      const captureFetch: typeof fetch = async (input, init) => {
        const payload = JSON.parse(String(init?.body))
        const focalId = requestContext.participants[0].characterId
        payload.state.context.currentState.researchAffection = { towardCharacterId: requestContext.participants[1].characterId, value: affection[focalId], scale: '-1 hostility, 0 indifference, +1 affection; own private state, separate from native bond' }
        if (Buffer.byteLength(JSON.stringify(payload)) > 64000) throw new Error('Rating exceeds budget input bound')
        const call = budget.reserve(reservations.rating)
        save(`${prefix}-call-${call}-request.json`, { call, stage: 'rating', modelId: JEV_MODEL_ID, payload })
        try {
          const response = await fetch(input, { ...init, body: JSON.stringify(payload) })
          // Read once under a strict size limit, then give the untouched JSON text back to native validation.
          const reader = response.body?.getReader()
          const chunks: Uint8Array[] = []
          let size = 0
          if (reader) try { while (true) { const chunk = await reader.read(); if (chunk.done) break; size += chunk.value.length; if (size > 64000) { await reader.cancel(); throw new Error('Oversized rating') }; chunks.push(chunk.value) } } finally { reader.releaseLock() }
          const text = Buffer.concat(chunks).toString('utf8')
          const parsed = parseCompletion(text)
          save(`${prefix}-call-${call}-response.json`, { call, stage: 'rating', status: response.status, structuredOutput: safeJevPayload(parsed), invalidJson: !parsed })
          completedCalls++
          return new Response(text || null, { status: response.status, headers: { 'Content-Type': 'application/json' } })
        } catch { save(`${prefix}-call-${call}-failure.json`, { call, stage: 'rating', failed: true }); completedCalls++; throw new Error('Sanitized rating failure') }
      }
      const result = await runJevInteraction(requestContext, async request => {
        const privateStates = requestContext.participants.map(person => ({ characterId: person.characterId, towardCharacterId: ids.find(id => id !== person.characterId), researchAffection: affection[person.characterId] }))
        const extension = request.stage === 'dialogue'
          ? `\nResearch-only private affective states: ${JSON.stringify(privateStates)}. Each value is that character’s own current romantic affection, -1 hostility, 0 indifference, +1 affection. It is separate from the broad social bond. Let it influence their speech naturally; never mention numbers. A character cannot know the counterpart’s private value. Follow the selected focal intention; these states do not override it.`
          : '\nRESEARCH OBSERVATION EXTENSION: In addition to every required native field, return researchObservations: an array with exactly one item per resident, {listenerId,speakerId,value,evidenceLineId,quote}. value is the listener’s perception of warmth expressed TOWARD THEM by the counterpart’s actual spoken words: -1 strongly hostile, 0 neutral/ambiguous, +1 strongly affectionate. This is not the listener’s own liking or the speaker’s hidden feelings. Use only the warmth or hostility expressed in counterpart utterances; do not rate whether the listener likes that warmth, and do not invert the value for a reserved or contrary listener. Never infer from private states, native bond scores, disposition-based response laws, or memories. speakerId must identify the counterpart. evidenceLineId must reference their spoken line, and quote must copy its complete speech exactly. A neutral value still needs a counterpart line. The extra observations do not alter ordinary appraisal/grounding checks.'
        const userMessage = request.userMessage + extension
        if (Buffer.byteLength(request.systemMessage + userMessage) + 4096 > 32768) throw new Error('Completion exceeds budget input bound')
        const expectedModel = request.stage === 'dialogue' ? configuredModel : TWO_PASS_MODEL_ID
        if ((request.modelId || configuredModel) !== expectedModel || request.settings.maxTokens !== (request.stage === 'dialogue' ? 16000 : 1536) || request.settings.temperature !== (request.stage === 'dialogue' ? 0.8 : 0.2)) throw new Error('Completion configuration drift')
        const call = budget.reserve(reservations[request.stage])
        save(`${prefix}-call-${call}-request.json`, { call, stage: request.stage, modelId: request.modelId || configuredModel, settings: request.settings, systemMessage: request.systemMessage, userMessage })
        try {
          const modelId = request.modelId || configuredModel!
          const response = await provider.transport({ id: `${prefix}-${call}`, fixtureId: spec.id, variant: 'baseline', repetition: step + 1, modelId, pricing: null, systemMessage: request.systemMessage, userMessage, promptSha256: createHash('sha256').update(request.systemMessage + userMessage).digest('hex'), conservativeInputTokenBound: Math.max(32768, Buffer.byteLength(request.systemMessage + userMessage) + 4096), context: requestContext, settings: { ...request.settings, topP: modelId.includes('anthropic.') || modelId.includes('deepseek.') ? null : 0.9 } }, request.signal)
          const content = finalTextOnly(response.finalText)
          save(`${prefix}-call-${call}-response.json`, { call, stage: request.stage, finalText: content, usage: response.usage, stopReason: response.stopReason })
          if (request.stage === 'appraisal') observations = parseCompletion(content)?.researchObservations
          completedCalls++
          return content
        } catch { save(`${prefix}-call-${call}-failure.json`, { call, stage: request.stage, failed: true }); completedCalls++; throw new Error('Sanitized completion failure') }
      }, { fetch: captureFetch, random: () => { const draw = random(); draws.push(draw); return draw }, onStatus: event => status.push(event) })
      const next = advanceResearch(requestContext, affection, coefficients, result, observations, h)
      if (next.accepted) { context = next.context; affection = next.affection; acceptedSteps++ }
      const matchedControl = controls.find(control => control.caseId === spec.id)!.points[acceptedSteps]
      const row = { caseId: spec.id, seed, step: step + 1, acceptedStep: acceptedSteps, focalId: requestContext.participants[0].characterId, modelTime: acceptedSteps * h, accepted: next.accepted, beforeContext: requestContext, beforeAffection, draws, result, observations, updates: next.updates, afterContext: context, afterAffection: affection, matchedControl, status, cumulativeCalls: budget.calls, reservedUsd: budget.reservedUsd }
      save(`${prefix}-encounter.json`, row)
      summary.push({ caseId: spec.id, seed, step: step + 1, acceptedStep: acceptedSteps, modelTime: row.modelTime, accepted: next.accepted, affection, result: result.success ? next.accepted ? 'accepted' : 'invalid-research-observation' : result.reason, updates: next.updates, matchedControl })
      console.log(JSON.stringify({ caseId: spec.id, seed, step: step + 1, accepted: next.accepted, calls: budget.calls }))
      // A deadline can race a pending SDK call. Stop the whole pilot, never start another encounter.
      if (status.some(event => event.reason === 'deadline' || event.reason === 'aborted') || completedCalls === 0) { stopped = true; break }
    }
  }
  save('summary.json', { completedAt: new Date().toISOString(), encountersAttempted: summary.length, accepted: summary.filter(row => row.accepted).length, providerRequests: budget.calls, dispatchedReservationsUsd: budget.reservedUsd, ledgerReservedUsd: 4 * steps * encounterReservation, actualBilledUsd: null, stoppedEarly: stopped, rows: summary })
  provider.close()
  console.log(JSON.stringify({ complete: true, output: root, providerRequests: budget.calls }))
}
main().catch(() => { console.error('Pilot stopped; sanitized failure. Inspect already-written artifacts. No retry was attempted.'); process.exitCode = 1 })
