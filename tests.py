from old import PreflopTier, classifyPreflop

##TEST 1 - checking the accuracy of the preflop tier assignment

#tested with only two suits but this is correct. additional suits have same logic and will work because suit logic only
# checks equality and performs no suit-specific logic.
cards = ['2','3','4','5','6','7','8','9','T','J','Q','K','A']
#suits = ['d', 's', 'h', 'c']
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



##TEST 1 - checking the accuracy of the preflop tier assignment