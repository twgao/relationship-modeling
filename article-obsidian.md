# Testing relationship models in Fable

Context: working on creating worlds with AI characters that change and evolve by themselves

How characters change

* talking to each other and learning new information from what’s said. In scenes with the player, they can also remember dialogue and player actions happening around them.
* reacting by updating their relationship scores, stress, energy, and social needs. A commitment made in conversation can also become a goal.
* bringing selected memories, recent conversation summaries, and their current state into later interactions. A separate reflection step when they go to sleep can also change their personality over time.

For this experiment, I focused on direct conversations and kept the personalities and response coefficients fixed.

| Quantity                          | Definition                                                | Details                                                                                                                 |
| --------------------------------- | --------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Affection, $r$                    | One character’s feeling toward the other.                 | Positive = affection; zero = indifference; negative = hostility. Unbounded in the equations; clipped to −1…+1 in Fable. |
| Own-response coefficient, $a$     | How a feeling changes on its own.                         | Assigned: positive amplifies the current feeling; negative lets it fade; zero adds no change through this term.         |
| Partner-response coefficient, $b$ | How strongly a character responds to the incoming signal. | Assigned: positive reciprocates; negative opposes. A larger magnitude means a stronger response.                        |
| Incoming signal, $u$              | What the character responds to.                           | The partner’s feeling in the equations; Scout’s quote-backed warmth rating, −1…+1, in Fable.                            |
| Noise strength, $\sigma$          | The size of added Gaussian disturbances.                  | 0, 0.05, or 0.15 in the mathematical runs. No Gaussian noise added to the conversations.                                |
| Model time, $t$                   | Arbitrary units, not minutes or days.                     | Each accepted conversation advances time by 0.5; a rejected attempt advances it by zero.                                |

I kept this experimental affection score separate from Fable’s existing relationship score. Susan’s affection toward George and George’s affection toward Susan are also separate values.

I first checked the mathematical model, $\dot r=ar+bu$. The dot means the rate of change in affection; the two terms combine the response to an existing feeling with the response to a partner.

Romeo reciprocates Juliet’s feelings, while Juliet opposes Romeo’s. Their feelings cycle rather than settling. Susan’s feelings reinforce themselves and respond twice as strongly to George. George’s feelings fade on their own and oppose Susan’s. These rules also produce a cycle, with a different shape. Other choices give different outcomes: cautious reciprocators can approach indifference, while reinforcing an oscillation can produce an expanding spiral.

Both ideal cycles take $2\pi$ units of model time. Romeo and Juliet are simultaneously affectionate for **25%** of a cycle; Susan and George are for **12.5%**.

![Ideal relationship cycles and their vector fields, overlaid with simulations at three noise levels.](https://raw.githubusercontent.com/twgao/relationship-modeling/main/figures/08-noise-overlay.png)

*Each point represents both characters’ feelings. Arrows show the direction of change. Black curves are the mathematical predictions; colored paths are individual simulations; dashed curves are their averages.*

**The simulations without noise reproduce the predicted cycles.** I then added small, zero-mean Gaussian disturbances to each feeling while keeping the starting values fixed. Variance describes how widely those disturbances vary; tripling the noise strength multiplies their variance by nine.

I ran **8,000 noisy trajectories**: 2,000 per couple at each of two noise levels ($\sigma=0.05$ and $0.15$), plus two checks without noise. Each runs for one ideal cycle. Larger noise spreads out the individual paths, while their average stays close to the ideal curve. More simulations estimate the spread more precisely; they do not reduce it.

I also measured the time spent mutually affectionate. At the higher noise level, Romeo–Juliet averaged **22.6%** of a cycle, with the middle 95% of runs ranging from 13.5–29.0%. Susan–George averaged **9.7%**, with a middle 95% range of 0–15.2%. These ranges describe differences between runs. The average curve can look ideal while individual couples spend less time mutually affectionate.

To connect this to Fable, I changed the input to **warmth expressed in the partner’s words**. I used the existing pipeline: **Jev → sampled approach → conversation → appraisal → updated feelings**. Jev rates approaches using one character’s current feelings and context. A sampled approach guides Kimi, which writes both voices. Scout assesses the exchange and supplies a warmth rating supported by an exact quote. The response rule updates affection, and the new feeling and conversation history feed the next encounter.

I assigned the response rules directly and checked whether the recorded updates followed them.

The pilot had **four trajectories: two per couple, five attempted conversations each**. That produced 20 attempts, 19 accepted conversations, and 60 model requests. One failed validation and changed no state. Each accepted conversation advanced half a unit of model time. I added **no Gaussian noise** here; variation came from sampled approaches, generated dialogue, and model ratings.

![Recorded Fable affection updates compared with their assigned response rules.](https://raw.githubusercontent.com/twgao/relationship-modeling/main/figures/09-conversation-dynamics.png)

*Replaying the assigned rule on the recorded warmth ratings matches the saved states. This verifies the updates without establishing a full conversational cycle.*

Susan’s two traces follow the predicted rise, $0.2e^t$, until they hit the upper bound. Every George-to-Susan warmth rating was zero, so her increase came entirely from self-reinforcement. Juliet’s affection fell when Romeo’s words were rated warm, as her response rule requires.

I included three consecutive accepted encounters from each run below. Each encounter has its complete recorded dialogue; the labels keep the separate conversations distinct.

> [!quote]- Romeo–Juliet: affection moves in opposite directions
>
> Run 1, attempts 1–3. All three were accepted.
>
> **Attempt 1**
>
> > **Romeo:** This quiet almost asks a question, doesn't it?
> >
> > **Juliet:** It asks for silence. I find that answer enough.
> >
> > **Romeo:** I'd rather hear what you're not saying.
>
> **Attempt 2**
>
> > **Juliet:** The quiet's grown louder since you gave it a job.
> >
> > **Romeo:** Then it's earning its keep. I can hear it working.
>
> **Attempt 3**
>
> > **Romeo:** Is the quiet still working for you, or should we give it a different job?
> >
> > **Juliet:** It's employed. I don't micromanage.
>
> I recorded Juliet’s affection falling from 0 to −0.5, then −1, after Scout rated Romeo’s quoted line as warmth 1 in each of the first two encounters. In attempt 2, Scout also rated Juliet’s line as 1, and Romeo’s affection rose from 0.2 to 0.7. Both ratings were zero in attempt 3, so neither affection value changed.
>
> [Read the complete run](https://github.com/twgao/relationship-modeling/blob/main/conversations/romeo-juliet-run-1.md).

> [!quote]- Romeo–Juliet: returning to the question of silence
>
> Run 2, attempts 3–5. All three were accepted.
>
> **Attempt 3**
>
> > **Romeo:** I keep thinking about what you said earlier. The quiet still feels... uncertain.
> >
> > **Juliet:** We're still here. That doesn't have to mean anything more.
> >
> > **Romeo:** I suppose I'm just trying to understand what 'here' means for us.
>
> **Attempt 4**
>
> > **Juliet:** We've almost made a ritual of questioning the quiet.
> >
> > **Romeo:** I might just like the sound of your answers.
>
> **Attempt 5**
>
> > **Romeo:** What would happen if we stopped questioning the quiet?
> >
> > **Juliet:** Then it would just be quiet. We'd have nothing to say.
> >
> > **Romeo:** I think I'd miss the sound of your answers.
>
> I recorded zero warmth in both directions in attempt 3. In attempts 4 and 5, Scout rated Romeo’s quoted lines as 1 and Juliet’s as zero. Juliet’s affection moved from 0 to −0.5 to −1; Romeo’s stayed at 0.2. The earlier rejected attempt 2, included in the full run, changed no state.
>
> [Read the complete run](https://github.com/twgao/relationship-modeling/blob/main/conversations/romeo-juliet-run-2.md).

> [!quote]- Susan–George: what happens after the ceasefire
>
> Run 1, attempts 3–5. All three were accepted.
>
> **Attempt 3**
>
> > **Susan:** What does this feel like to you? Just sitting here, no pressure to be anything.
> >
> > **George:** Like a ceasefire. Temporary, but I'm not complaining.
> >
> > **Susan:** I wasn't looking to negotiate terms, you know.
> >
> > **George:** Neither was I. That's why it's working.
>
> **Attempt 4**
>
> > **George:** I keep thinking about the 'temporary' part of that ceasefire. What happens when the truce ends?
> >
> > **Susan:** Then we figure out the next step together. No ambush.
>
> **Attempt 5**
>
> > **Susan:** Earlier you wondered what happens when our 'truce' ends. What would need to be different for it to feel like more than a ceasefire to you?
> >
> > **George:** I think the fact that I'm still calling it a ceasefire answers that. I'm not there yet.
>
> I recorded zero warmth in both directions throughout these three encounters. George’s affection stayed at zero. Susan’s rose from about 0.544 before attempt 3 to 1 after attempt 4, then stayed at the bound. That increase came from her assigned self-reinforcement term, not from a positive rating of George’s words.
>
> [Read the complete run](https://github.com/twgao/relationship-modeling/blob/main/conversations/susan-george-run-1.md).

> [!quote]- Susan–George: trying to find the first sentence
>
> Run 2, attempts 3–5. All three were accepted.
>
> **Attempt 3**
>
> > **Susan:** We keep circling it. The plain talk I asked for.
> >
> > **George:** I remember. Just... trying to find the right first sentence.
> >
> > **Susan:** Then let's start with now. How this silence feels.
> >
> > **George:** It feels... heavy. Like we're both waiting to be misunderstood.
>
> **Attempt 4**
>
> > **George:** I'm still circling that first sentence. Worried I'll pick the wrong one and we'll be back here again next week.
> >
> > **Susan:** Then let's stop circling. I'll start: I feel like we're standing still while you find the perfect words.
>
> **Attempt 5**
>
> > **Susan:** We could just sit for a bit. No perfect sentences required.
> >
> > **George:** That's... a novel approach. I think I can manage that.
>
> I recorded zero warmth in both directions in attempts 3 and 4. In attempt 5, Scout rated Susan’s line as 1, and George’s assigned rule moved his affection from 0 to −0.393. Susan was already at 1 and remained there. George’s reply was generated before the numerical update.
>
> [Read the complete run](https://github.com/twgao/relationship-modeling/blob/main/conversations/susan-george-run-2.md).

The warmth measurement was coarse: **31 of 38 accepted directional ratings were zero; the other seven were one**. Different conversations often became the same number. Updating between conversations also changes the dynamics, and these runs cover less than half an ideal cycle.

I reproduced the mathematical cycles and verified the assigned response rules operating on real generated dialogue. I would need longer runs and better-calibrated warmth ratings before claiming that the conversations reproduce complete cycles.

Code, results, and graphs are on [GitHub](https://github.com/twgao/relationship-modeling).
