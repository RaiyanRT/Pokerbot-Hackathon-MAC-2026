"""Your tournament bot. Keep this file named main.py.

Test it locally:

    macpoker play main.py house:call house:random --deals 50

Add --subprocess for full production parity. You can split your code into
extra modules in this folder and import them from here; zip the whole folder
(main.py at the root) when you submit.

Full SDK reference: https://docs.poker.monashcoding.com
"""

from macpoker import Bot


class MyBot(Bot):
    def act(self, state):
        # What you can see:
        #   state.hole          your two cards, e.g. ["As", "Kd"]
        #   state.board         community cards dealt so far
        #   state.pot           chips in the middle
        #   state.to_call       chips you must add to stay in the hand
        #   state.stacks        every seat's remaining chips
        #   state.min_raise_to  smallest legal raise-to amount
        #   state.max_raise_to  raise-to amount that puts you all in
        #   state.history       every action this hand: [street, seat, kind, amount]
        #   state.clock_ms      time left on your clock
        #
        # What you can do:
        #   state.check() / state.call() / state.fold()
        #   state.raise_to(amount) / state.all_in()

        if state.to_call == 0:
            return state.check()

        pot_odds = state.to_call / (state.pot + state.to_call)
        if pot_odds < 0.3:
            return state.call()
        return state.fold()
