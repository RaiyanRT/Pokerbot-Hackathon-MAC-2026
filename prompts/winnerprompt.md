You won generation [N]. Your bot is the current champion. Below are this
generation's results and the code of every bot.

Next generation: the other three models have your code and are trying to
improve it to beat you. The next table will be your new bot, their three new
bots, and a frozen copy of your current champion. Fitness is average
placement points over [K] duplicate sets, plus results against a fixed
gauntlet (house:call, house:random, house:allin, house:checkfold) at 4-6 seats.

Improve your bot without rewriting it. Keep the architecture and make targeted
changes: parameter tweaks, bug fixes, or processes you hadn't thought of. Use
the other bots for ideas: any small process they did better than you, and anything they
exploit in your play. Your opponents will think like your own code, so also
look for ways a near-copy of you could exploit you, and close them.

Rules, API and hard constraints are unchanged from the original brief:
[paste the original brief if this is a new conversation]

Results this generation:
[bot | model | placement pts | game pts | chips/game | verdicts]

Bots:
--- Champion (yours) ---
[code]
--- [model], placed [x] ---
[code]
(...one block per bot)

Output:
1. A changelog: each change, why you made it, and the test evidence for it.
2. An updated docstring (3-5 sentences).
3. The complete main.py in a single code block.
4. One line on what you ran or tested.