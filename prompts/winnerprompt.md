You are improving a poker bot for the MAC no-limit Texas Hold'em bot tournament. Read this entire brief, including the full game rules and API reference, before designing anything. Everything you need is in this brief. The official docs below are optional extra reference if you can browse.

This is generation {GEN} of an evolutionary process. Each generation, five bots play a league against each other, against every past champion and against the house bots. The bot with the most placement points becomes champion and goes into the next generation unchanged, alongside four new variants written to beat it. A variant that does not beat the champion is simply discarded, so a real attempt at improvement costs nothing.

Your bot, {CHAMPION}, won generation {PREV_GEN}. It goes into generation {GEN} unchanged, as one of your opponents. Your job is to write a variant of it that beats it.

=== WHAT YOU ARE GIVEN ===
- The complete main.py of every generation {PREV_GEN} bot, pasted at the end of this brief and labelled by folder name only (bot_a, bot_b, ...).
- The champion is {CHAMPION}.
- Generation {PREV_GEN} league results (placement points are out of 5 at a five-bot table; higher is better; ties in placement are broken by game points):

{PASTE results/gen{PREV_GEN}.csv HERE, WITH THE model COLUMN DELETED}

- Extra notes from testing, if any: {PASTE h2h.py RESULTS OR OBSERVATIONS, OR WRITE "none"}

Use these bots as a source of ideas only. The real tournament is against other teams' bots that nobody has seen. Do not add logic that detects, targets or is tuned to any specific bot here; improve how your bot plays against an unknown field.

=== YOUR TASK ===
Starting from {CHAMPION}, write an improved version that earns more placement points than the original against a varied, unknown field. Study the results and the other bots for weaknesses in the champion and ideas worth borrowing. Keep what works.

How your bot will be judged: it plays a league against the unchanged champion, the other new variants, every past champion and the house bots, scored exactly as described in the game rules below. A TLE, RTE or PV verdict in any game disqualifies it from becoming champion, so robustness comes before cleverness. Prefer focused improvements you can justify over a full rewrite, unless you have a clear reason. The result must still be one complete, standalone main.py.

## Read the rules first

If you can browse, you may also read these official pages before designing the bot:

- https://docs.poker.monashcoding.com/writing-a-bot/
- https://docs.poker.monashcoding.com/game-format/ and its pages on duplicate deals, information, clocks and scoring
- https://docs.poker.monashcoding.com/rules/
- https://docs.poker.monashcoding.com/faq/

If an official page conflicts with this brief, follow the page and explain the conflict briefly.

=== GAME RULES ===
The table and each hand
- No-limit Texas Hold'em. Tournament tables have 4 to 6 bots depending on turnout (the engine supports 2 to 9). Never hardcode the table size; read state.num_players.
- Blinds are 1 (small) and 2 (big) and never increase. There are no antes.
- Every hand starts with every bot on a fresh 200-chip stack (100 big blinds). Stacks reset every hand, so nobody is ever eliminated and going all in is an ordinary bet, not a survival decision. The most you can lose in one hand is 200 chips.

A game
- A game is 100 hands. Each hand is dealt from a freshly shuffled deck.
- The button moves one seat every hand, so every bot plays every position equally often. In the engine the button is always seat 0 and the bots rotate through the seats; work out your position from state.seat, state.button and state.num_players.
- Your score for a game is your net chips won or lost over all 100 hands.

A round: duplicate deals
- A table of N bots plays N games per round (5 games at a 5-bot table).
- All N games deal the same 100 decks: hand 1 uses the same deck in every game, hand 2 uses the same deck in every game, and so on.
- Each game shifts every bot one seat along, so by the end of the round every bot has played every hand from every seat, exactly as its opponents did. Card luck cancels out; decisions separate the scores.
- Each game starts your bot as a fresh process with a read-only filesystem. Nothing carries over between games, so keep all memory on self and expect it to start empty every game.

Opponents and information
- You play all of a round's games against the same opponents. Tables are redrawn between rounds.
- Opponents are anonymous: you are never told names or teams. Each has a player id that stays fixed for the whole game (ids reset between games). Seats change every hand, so key any opponent statistics by player id, never by seat. state.players and the "players" field on events map seat to player id.
- Folded hands are never shown. Opponents' hole cards are revealed only at showdown, and only for players still in the hand. A hand won because everyone else folded reveals nothing.
- You see every public action as it happens. Nothing about earlier hands is provided later; if you want history, record it yourself in the observer hooks.
- The field will include unknown bots of very different styles: passive, hyper-aggressive, random and strong.

Clock and verdicts
- Each bot has a chess clock: a 30-second bank at the start of each game plus 0.1 s added every hand. There is no per-move limit; the clock runs only while the engine waits on your bot.
- Averaging 0.1 s or less of thinking per hand never shrinks the bank; more than that spends it down. state.clock_ms gives the time left at every decision.
- Verdicts: OK (played the whole game), TLE (ran out of clock), RTE (crashed or the process died), PV (broke the wire protocol). Any TLE, RTE or PV makes your bot check-fold for the rest of that game: it keeps posting blinds and folding to every bet, bleeding chips until the game ends.

Scoring
- Game points: at the end of each game, bots are ranked by that game's chips. 1st gets N points, 2nd gets N-1, down to 1 for last (5 to 1 at a 5-bot table).
- Placement points: each bot's game points are summed over the round's N games and ranked the same way, N for the best total down to 1. Ties share the average of the places they cover (two bots tied for 2nd at a 5-bot table get 3.5 each).
- Worked example at a 5-bot table: a bot finishing 1st, 2nd, 1st, 3rd and 2nd in the five games scores 5+4+5+3+4 = 21 game points. If 21 is the best total at the table, it gets 5 placement points for the round.
- Chip margins only decide the order within a game: winning a game by 500 chips earns the same game points as winning it by 5.
- Round 1 tables are random. After each round, tables are regrouped by cumulative placement points (ties broken by total game points), so you increasingly face bots of similar strength.
- The tournament is 4 rounds. The sum of round placement points decides the final standings; ties for a prize are settled by a head-to-head set between the tied bots.

Rules of conduct (breaking any of these disqualifies the team; every submission is read by the organisers)
- Python 3.12 sandbox with only the standard library, numpy and the macpoker SDK. An unavailable import fails validation.
- No network access of any kind (the sandbox has none). No AI or LLM calls at runtime.
- Compute only on your own turn: inside act() and the observer hooks. No background threads, no extra processes, no work scheduled while opponents act.
- No teaming: the bot plays for itself alone and must not recognise, signal to, soft-play or pass chips to any other bot.
- No interference: do not read anything outside your own bot, exhaust shared resources, or try to recover hidden information such as unseen cards or deck order by any means other than playing.

=== HARD CONSTRAINTS ===
- main.py defines exactly one Bot subclass (or a module-level bot = MyBot() instance). Keep all code in main.py.
- Wrap all decision logic in try/except and fall back to a safe legal action (check if to_call == 0, otherwise fold).
- Wrap observer hooks in try/except too; a crash there is also fatal.
- Only raise when state.can_raise is true, with min_raise_to <= n <= max_raise_to.
- Use only the fields, methods and event keys documented below. Do not invent undocumented SDK fields or event keys.
- Target an average decision time under 30 ms. If state.clock_ms runs low, switch to a fast fallback.

=== API REFERENCE ===
A complete, working main.py (it just calls every bet). Build your bot from this shape:

from macpoker import Bot

class MyBot(Bot):
    def act(self, state):
        return state.call()

Actions (return one from act):
- state.check()        legal only when state.to_call == 0
- state.call()         match the current bet
- state.fold()
- state.raise_to(n)    raise so your TOTAL bet this street becomes n (raise-to, not increment); n must be between min_raise_to and max_raise_to
- state.all_in()       raise to state.max_raise_to
Illegal actions are coerced (impossible raise -> call, checking a bet -> fold, raise amounts clamped). Do not rely on this; check the fields.

State fields:
- hole: list[str], e.g. ["As","Td"]. Ranks 2-9 T J Q K A, suits s h d c.
- board: list[str], 0, 3, 4 or 5 cards. street: "preflop"/"flop"/"turn"/"river".
- hand: int (hand number in game). seat: int (your seat this hand). button: int (button seat; the button is always seat 0).
- pot: int. to_call: int (0 = may check). min_raise_to, max_raise_to: int. can_raise: bool.
- stacks: list[int] per seat. street_bets: list[int] per seat this street. my_stack: int.
- players: list[int] (player id per seat this hand). player: int (your id).
- player_at(seat) -> id. seat_of(player) -> seat.
- folded: list[bool] per seat. num_players: int. players_in_hand: int.
- history: list of [street, seat, kind, amount] for every action this hand.
- clock_ms: int (ms left on your clock).
There is no equity calculator and no pot-odds helper; you must implement any maths yourself.

Optional observer hooks (no-ops by default):
    def on_match_start(self, info): ...   # game config, blinds, clocks
    def on_hand_start(self, info): ...    # your seat and hole cards
    def on_action(self, event): ...       # every action by every seat
    def on_street(self, event): ...       # board reveals
    def on_hand_end(self, info): ...      # results, revealed cards, pots
    def on_match_end(self, info): ...     # final chip totals
The hand_start, action, street and hand_end events carry "players" (seat -> player id). The match_start (hello) and match_end messages do NOT include "players". Example:
    def on_action(self, event):
        who = event["players"][event["seat"]]
        if event["action"] == "raise":
            self.raises[who] += 1
Event shapes (from the wire protocol):
- action: {"hand", "street", "seat", "action", "amount", "pot", "players"}
- street: {"hand", "street", "board", "players"}
- hand_end: {"hand", "board", "deltas" (per seat), "revealed" {seat_str: [cards]}, "pots" [{"amount","winners"}], "players"}
- match_start/hello: {"player", "num_players", "num_hands", "stack", "blinds", "time_bank_ms", "increment_ms"}
print() is safe (goes to the game log).

=== LOCAL TESTING ===
macpoker play main.py house:call house:random house:allin house:checkfold --deals 100
House bots: call (calls everything), checkfold (folds to any bet), allin (shoves always), random.

=== OUTPUT ===
1. In 2 to 4 sentences: what you changed from the champion and why you expect it to score more placement points.
2. The official pages you actually read, or "none; used the brief." Do not list pages you did not open.
3. A docstring at the top of main.py summarising your strategy in 3 to 5 sentences.
4. The complete, runnable main.py in a single code block. Do not omit any code.
5. One line saying whether you ran or tested the code. Do not claim tests you did not run.

=== GENERATION {PREV_GEN} BOTS ===
{PASTE EACH BOT HERE AS "### bot_x/main.py" FOLLOWED BY ITS FULL CODE IN A CODE BLOCK}
