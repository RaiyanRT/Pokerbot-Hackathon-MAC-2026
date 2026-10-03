"""Your tournament bot. Keep this file named main.py.

Test it locally:

    macpoker play main.py house:call house:random --deals 50

Add --subprocess for full production parity. You can split your code into
extra modules in this folder and import them from here; zip the whole folder
(main.py at the root) when you submit.

Full SDK reference: https://docs.poker.monashcoding.com
"""

from macpoker import Bot

from enum import IntEnum


class OppData():
    def __init__(self, id: int):
        self.id = id
        self.vpip = None #voluntary participation in hands = #played / total hands
        self.pfr = None #preflop raise % = preflop raise hands / total hands
        self.three_bet = None #reraise a preflop rase % = 3 bet opportunities taken / 3 bet opportunities
        self.show_down = None #how often do they make it to showdown after making it to flop = times in showdown / times in flop
        self.show_down_win = None # how often do they win at showdown = win @ showdown / showdown
        self.biggest_preflop_called = None # ratio multiplier representing the largest raise preflop that was by this player i.e. if pot was 2 and I bet 6 i.e. 3 times pot than = 3
        self.biggest_preflop_raised = None # biggest preflop raise they made that someone called i.e. in prev example = 3
        self.cbet = None # % of time they cbet after being aggressor preflop = 2 cbets / 2 pre flop raises = 100%

class myData():
    def __init__(self):
        self.pot_odds = None # equity I need for a call to be break-even over a large number of simulations = 30 in pot and 10 to call = 10 / 30 + 10 = 
        #10 / 40 = 25% equity for the call to be breakeven. If I have less equity than this I should fold.

#equity is based in 4 parts
#preflop - flop - turn - river

class CommunityData():

    def __init__(self):
        #cards
        self.flop = None
        self.turn = None
        self.river = None

        #suits
        self.diamonds = None
        self.hearts = None
        self.clubs = None
        self.spades = None

        #straights
        self.cards_to_straight = None
        self.combinations_to_make_straight = None

        #paired cards
        self.pairs = None
        self.trips = None
        self.quads = None


def transform_to_numbers(cards: list[str]): ### NOTE NOT TESTED YET
    values = []
    for card in cards:
            if card[0] == ace and 1 not in values:
                values.append(1)
                values.append(14)
            elif card[0] == king and 13 not in values:
                values.append(13)
            elif card[0] == queen and 12 not in values:
                values.append(12)
            elif card[0] == jack and 11 not in values:
                values.append(11)
            elif card[0] == ten and 10 not in values:
                values.append(10)
            else:
                if int(card) not in values:
                    values.append(int(card))

    return values



def cards_to_straight(cards: list[str]): ### NOTE NOT TESTED YET
    """
    calculates how many cards are the minimum to form a straight
    also returns the range in which those cards must come from

    calculate by checking each of the 11x 5-card windows starting from A-5 up to 10-A

    returns the number of cards needed for a straight, the range, and the specific cards needed
    #enumerates all possible cards for minimum distances to straights. If a larger straight can be formed (i.e. the board 2 3 4 6) then it 
    should be enumerated so long as the number of cards required to form it is <=2
    """

    values = transform_to_numbers(cards)
    values.sort() #sorted numbs
    cards_to_straight = 5
    missing_cards = []
    starts = []
    ends = []
        # starting range of the straight
    for i in range (1, 11):
        offset = 4 # the end of the window
        cap = i + offset
        current = 0
        for value in values:
            if value <= cap:
                current +=1

        #if equal - there might be multiple straights possible so append multiple values
        if current == cards_to_straight or current <= 2:
            starts.append(i)
            ends.append(i+offset)

        #if less than - this is the minimum thus far so make new arrays
        if current < cards_to_straight:
                    cards_to_straight = current
                    starts = [i]
                    ends = [i+offset]

    #find the specific cards that need to be there
    for j in range(len(starts)):
        for i in range(start, end+1):
            if i not in values:
                missing_cards[j].append[i]

    return [cards_to_straight, starts, ends, missing_cards]


#FLOP
#I need to know - is paired? is straight connected? is suited?
def board_stats(cards: list[str]): ### NOTE NOT TESTED YET
    """
    Tells me
    - how many of each suit

    
    """
    diamonds = 0
    hearts = 0
    clubs = 0
    spades = 0 # diamonds, hearts, clubs, spades
    flush_type = None #the type of the cards closest to a flush
    flush_cards = 0 # the number of cards on the board with that type
    cards_to_flush = 5

    pairs = []
    trips = []
    quads = []

    cards_to_straight = 0

    #check suit types
    for i in range(len(cards)):
        if cards[i][1] == 'd':
            diamonds +=1
        elif cards[i][1] == 'h':
            hearts +=1
        elif cards[i][1] == 'c':
            clubs +=1
        elif cards[i][1] == 's':
            spades +=1

    #track what suit is most prominent
    flush_type = 'd'
    flush_cards = diamonds
    if hearts > flush_cards:
        flush_type = 'h'
        flush_cards = hearts
    if spades > flush_cards:
        flush_type = 's'
        flush_cards = spades
    if clubs > flush_cards:
        flush_type = 'c'
        flush_cards = clubs
    cards_to_flush = cards_to_flush - flush_cards # 5 - how many of the most prominent suit are on the board


    #track pairs, trips, quads
    seen = []
    for i in range(len(cards))-1:
        for j in range(i, len(cards)-1):
            counter = 0
            if cards[i][0] not in seen and (cards[i][0] == cards[j][0]):
                counter +=1

        if counter == 1:
            pairs.append(cards[i][0])

        elif counter == 2:
            trips.append(cards[i][0])

        elif counter == 3:
            quads.append(cards[i][0])
        
        seen.append(cards[i][0]) # ensure uniqueness

    #cards to straight
    straight_result = cards_to_straight(cards)


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
        return PreflopTier.Suited_Garbage

    #T11Garbage
    else: 
        return PreflopTier.Garbage

    



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


