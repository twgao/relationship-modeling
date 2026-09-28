# Testing relationship models in Fable

*Influenced by PHYS 4410 Nonlinear Dynamics.*

I wanted to see whether the relationship models from class would still work when the characters had to talk to each other. I tested this in Fable, where characters converse, react, and carry their history into the next encounter. I used Romeo and Juliet, plus the George-and-Susan example from *Seinfeld*, and added a numerical feeling toward the other person.

I started by checking the equations on their own. Positive feelings mean affection, negative feelings mean hostility, and zero means indifference. The two directions are separate: Susan liking George says nothing about George liking Susan.

The rule is $\dot r=ar+bu$. A feeling’s rate of change depends on its current value and an input from the partner. The first term can reinforce or fade an existing feeling; the second can reciprocate or oppose the input. In the mathematical version, that input is the partner’s current feeling.

Romeo reciprocates Juliet’s feelings, while Juliet opposes Romeo’s. Their feelings cycle rather than settling. Susan’s feelings reinforce themselves and respond twice as strongly to George. George’s feelings fade on their own and oppose Susan’s. These rules also produce a cycle, with a different shape. Other choices give different outcomes: cautious reciprocators can approach indifference, while reinforcing an oscillation can produce an expanding spiral.

Both ideal cycles take $2\pi$ units of model time. Romeo and Juliet are simultaneously affectionate for **25%** of a cycle; Susan and George are for **12.5%**.

![Ideal relationship cycles and their vector fields, overlaid with simulations at three noise levels.](https://raw.githubusercontent.com/twgao/relationship-modeling/main/figures/08-noise-overlay.png)

*Each point represents both characters’ feelings. Arrows show the direction of change. Black curves are the mathematical predictions; colored paths are individual simulations; dashed curves are their averages.*

**The simulations without noise reproduce the predicted cycles.** I then added small, zero-mean Gaussian disturbances to each feeling while keeping the starting values fixed. Variance describes how widely those disturbances vary; tripling the noise strength multiplies their variance by nine.

I ran **8,000 noisy trajectories**: 2,000 per couple at each of two noise levels ($\sigma=0.05$ and $0.15$), plus two checks without noise. Each runs for one ideal cycle. Larger noise spreads out the individual paths, while their average stays close to the ideal curve. More simulations estimate the spread more precisely; they do not reduce it.

I also measured the time spent mutually affectionate. At the higher noise level, Romeo–Juliet averaged **22.6%** of a cycle, with the middle 95% of runs ranging from 13.5–29.0%. Susan–George averaged **9.7%**, with a middle 95% range of 0–15.2%. These ranges describe differences between runs. The average curve can look ideal while individual couples spend less time mutually affectionate.

To connect this to Fable, I changed the input to **warmth expressed in the partner’s words**. I used the existing pipeline: **Jev → sampled approach → conversation → appraisal → updated feelings**. Jev rates approaches using one character’s current feelings and context. A sampled approach guides Kimi, which writes both voices. Scout assesses the exchange and supplies a warmth rating supported by an exact quote. The response rule updates affection, and the new feeling and conversation history feed the next encounter.

I bounded the added affection score between −1 and +1 and kept it separate from Fable’s ordinary relationship score. I assigned the response rules directly and checked whether the recorded updates followed them.

The pilot had **four trajectories: two per couple, five attempted conversations each**. That produced 20 attempts, 19 accepted conversations, and 60 model requests. One failed validation and changed no state. Each accepted conversation advanced half a unit of model time. I added **no Gaussian noise** here; variation came from sampled approaches, generated dialogue, and model ratings.

![Recorded Fable affection updates compared with their assigned response rules.](https://raw.githubusercontent.com/twgao/relationship-modeling/main/figures/09-conversation-dynamics.png)

*Replaying the assigned rule on the recorded warmth ratings matches the saved states. This verifies the updates without establishing a full conversational cycle.*

Susan’s two traces follow the predicted rise, $0.2e^t$, until they hit the upper bound. Every George-to-Susan warmth rating was zero, so her increase came entirely from self-reinforcement. Juliet’s affection fell when Romeo’s words were rated warm, as her response rule requires.

In one exchange:

> **Susan:** “We could just sit for a bit. No perfect sentences required.”
>
> **George:** “That's... a novel approach. I think I can manage that.”

Scout rated Susan’s words as warm. George’s assigned rule then moved his affection from **0 to −0.393**. His reply was generated before this update.

The warmth measurement was coarse: **31 of 38 accepted directional ratings were zero; the other seven were one**. Different conversations often became the same number. Updating between conversations also changes the dynamics, and these runs cover less than half an ideal cycle.

I reproduced the mathematical cycles and verified the assigned response rules operating on real generated dialogue. I would need longer runs and better-calibrated warmth ratings before claiming that the conversations reproduce complete cycles.

Code, results, and graphs are on [GitHub](https://github.com/twgao/relationship-modeling).
