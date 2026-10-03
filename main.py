"""Your tournament bot. Keep this file named main.py.

Test it locally:

    macpoker play main.py house:call house:random --deals 50

Add --subprocess for full production parity. You can split your code into
extra modules in this folder and import them from here; zip the whole folder
(main.py at the root) when you submit.

Full SDK reference: https://docs.poker.monashcoding.com
"""

from macpoker import Bot


class OppData():
    def __init__(self, id: int):
        self.id = id
        self.vpip = None #voluntary participation in hands = #played / total hands
        self.pfr = None #preflop raise % = preflop raise hands / total hands
        self.three_bet = None #reraise a preflop rase % = 3 bet opportunities taken / 3 bet opportunities
        self.show_down = None #how often do they make it to showdown after making it to flop = times in showdown / times in flop
        self.show_down_win = None # how often do they win at showdown = win @ showdown / showdown 

from enum import IntEnum
class PreflopTier(IntEnum):
    Premium = 1 # Tier 1: Strong Pockets (AA - QQ) + AK 
    Strong = 2 # Mid Pockets (JJ - 88) + AQ AJ AT
    Suited_Aces = 3 #  Suited Aces: (Ac 4c)
    Weak_Pockets = 4 # Weak Pockets (77 - 22)
    Suited_High_Cards = 5 #two high cards T+ that are suited
    High_Cards = 6 # Two high cards (QJ QK QT etc.)
    Suited_Connectors = 7 # Suited connectors (Tc9c)
    Offsuit_Ace = 8 #  Non Suited Aces: 
    Suited_One_Gaps = 9 # suited cards that are both higher than 7 and one card apart
    Suited_Garbage = 10 # Suited Garbage
    Garbage = 11 # Garbage

#variables
#NOTE - variables are not interchangeable there is overlap between definitions i..e J is in both high and mid bc they are for different cases
ace = 'A'
king = 'K'
queen = 'Q'
jack = 'J'
ten = 'T'
premium = ['A', 'K', 'Q']
mid = ['J', 'T', '9', '8'] #mid pockets
AtT = ['A', 'K','Q', 'J', 'T'] #
weak = ['7', '6', '5', '4', '3', '2']

def diff(c1: str, c2:str):
    cards = [c1, c2]
    values = []

    for card in cards:
        if card[0] == ace:
            values.append(14)
        elif card[0] == king:
            values.append(13)
        elif card[0] == queen:
            values.append(12)
        elif card[0] == jack:
            values.append(11)
        elif card[0] == ten:
            values.append(10)
        else:
            values.append(int(card[0]))

    return abs(values[0]-values[1])

def classifyPreflop(c1: str, c2: str):
    """takes starter hand and puts it in one of the following buckets. 
    Tier 1: Premium (AA - QQ) + AK 
    Tier 2: Strong  (JJ - 88) + AQ AJ AT
    Tier 3: Suited Aces: (Ac 4c)
    Tier 4: Weak Pockets (77 - 22)
    Tier 5: Two high cards (QJ QK QT etc.)
    Tier 6: Suited connectors (Tc9c)
    Tier 7: Non Suited Aces: 
    Tier 8: High Suited One Gaps: both cards 8+ and 1 gap apart and same suit
    Tier 9: Suited Garbage
    Tier 10: Garbage: 
    """

    #T1: Premium Tier Pockets + AK 
    if c1[0] == c2[0]: #pocket found

        if c1[0] in premium:
            return PreflopTier.Premium

        #T2 Strong
        elif c1[0] in mid:
            return PreflopTier.Strong

        #T4 weak pockets
        elif c1[0] in weak:
            return PreflopTier.Weak_Pockets

    #T1 AK Edge Case    
    elif (c1[0] is ace or c1[0] is king) and (c2[0] is ace or c2[1] is king):
        return PreflopTier.Premium 

    #T2 AQ AJ AT Edge Cases
    elif ((c1[0] == ace and c2[0] in AtT) or (c1[0] in AtT and c2[0] == ace)):
        return PreflopTier.Strong

    #T3 Suited Aces: 
    elif ((c1[0] is ace or c2[0] is ace) and c1[1] == c2[1]):
        return PreflopTier.Suited_Aces

    #T5 suited high cards 
    elif (c1[0] in AtT and c2[0] in AtT and c1[1] == c2[1]):
            return PreflopTier.Suited_High_Cards
    
    #T6 high cards:
    elif (c1[0] in AtT and c2[0] in AtT):
        return PreflopTier.High_Cards

    #T7 suited connectors:
    elif (c1[1] == c2[1] and diff(c1, c2) == 1):
        return PreflopTier.Suited_Connectors
    
    #T8 offsuit aces:
    elif ((c1[0] is ace or c2[0] is ace) and c1[1] != c2[1]):
        return PreflopTier.Offsuit_Ace

    #T9 High suited one gaps:
    elif ((c1[0] in mid and c2[0] in mid) and (c1[1] == c2[1]) and diff(c1, c2) == 2):
        return PreflopTier.Suited_One_Gaps
    
    #T10 suited garbage
    elif (c1[1] == c2[1]):
        return PreflopTier.Suited_Garbage\

    #T11Garbage
    else: 
        return PreflopTier.Garbage

    

#testing this is correct
cards = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']
#cards = ['8','9','T','J','Q','K','A']
suits = ['d','s']#clubs and hearts gone

deck = []

for suit in suits:
    for card in cards:
        deck.append(card + suit)

#print(deck)

tiers = [[] for _ in range(len(PreflopTier))]


for i in range(len(deck)):
    for j in range(i+1, len(deck)):
        c1 = deck[i]
        c2 = deck[j]
        res = classifyPreflop(c1, c2).value
        tiers[res-1].append(c1+c2)

for i in range(len(tiers)):
    print(f"Row ${i}: {PreflopTier(i+1).name} + {tiers[i]}")

#print(classifyPreflop('Td','Ks').value)

class MyBot(Bot):
    def act(self, state):
        self.opponents = [OppData(x) for x in range(6)]

        
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


