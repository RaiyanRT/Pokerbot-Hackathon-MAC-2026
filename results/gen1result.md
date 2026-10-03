Notes:

- Opus and Astra were very close to each other. Astra was able to take advantage of weaker bots slightly better, however Opus was stronger overall in terms of strategy
- The bots were so close to each other that I build a secondary script called h2h (Head to head) which runs the two bots against each other with three fillers to decide the winner
- Running the h2h script with 50 sets still made the models so extremely close to each other, it only took 100 sets to decide the winner


Head to head results:
set 1/100: game points 21 vs 22
set 2/100: game points 18 vs 20
set 3/100: game points 22 vs 23
set 4/100: game points 20 vs 21
set 5/100: game points 18 vs 15
set 6/100: game points 18 vs 19
set 7/100: game points 16 vs 19
set 8/100: game points 21 vs 20
set 9/100: game points 19 vs 20
set 10/100: game points 18 vs 18
set 11/100: game points 19 vs 20
set 12/100: game points 21 vs 16
set 13/100: game points 21 vs 16
set 14/100: game points 21 vs 15
set 15/100: game points 19 vs 18
set 16/100: game points 23 vs 22
set 17/100: game points 21 vs 21
set 18/100: game points 18 vs 22
set 19/100: game points 16 vs 17
set 20/100: game points 19 vs 20
set 21/100: game points 19 vs 17
set 22/100: game points 23 vs 16
set 23/100: game points 22 vs 22
set 24/100: game points 18 vs 20
set 25/100: game points 21 vs 18
set 26/100: game points 23 vs 16
set 27/100: game points 21 vs 20
set 28/100: game points 16 vs 18
set 29/100: game points 16 vs 19
set 30/100: game points 14 vs 17
set 31/100: game points 21 vs 19
set 32/100: game points 17 vs 17
set 33/100: game points 18 vs 17
set 34/100: game points 20 vs 16
set 35/100: game points 21 vs 17
set 36/100: game points 18 vs 18
set 37/100: game points 19 vs 19
set 38/100: game points 17 vs 19
set 39/100: game points 23 vs 14
set 40/100: game points 12 vs 17
set 41/100: game points 19 vs 20
set 42/100: game points 18 vs 24
set 43/100: game points 16 vs 15
set 44/100: game points 21 vs 14
set 45/100: game points 14 vs 15
set 46/100: game points 23 vs 20
set 47/100: game points 20 vs 19
set 48/100: game points 20 vs 16
set 49/100: game points 22 vs 18
set 50/100: game points 22 vs 21
set 51/100: game points 20 vs 21
set 52/100: game points 19 vs 18
set 53/100: game points 18 vs 15
set 54/100: game points 21 vs 20
set 55/100: game points 18 vs 20
set 56/100: game points 19 vs 21
set 57/100: game points 21 vs 22
set 58/100: game points 21 vs 23
set 59/100: game points 20 vs 19
set 60/100: game points 18 vs 18
set 61/100: game points 19 vs 20
set 62/100: game points 21 vs 19
set 63/100: game points 21 vs 18
set 64/100: game points 18 vs 21
set 65/100: game points 20 vs 22
set 66/100: game points 19 vs 16
set 67/100: game points 20 vs 21
set 68/100: game points 22 vs 16
set 69/100: game points 17 vs 20
set 70/100: game points 21 vs 20
set 71/100: game points 21 vs 20
set 72/100: game points 22 vs 19
set 73/100: game points 18 vs 18
set 74/100: game points 22 vs 19
set 75/100: game points 18 vs 18
set 76/100: game points 22 vs 19
set 77/100: game points 21 vs 19
set 78/100: game points 20 vs 21
set 79/100: game points 18 vs 17
set 80/100: game points 21 vs 21
set 81/100: game points 18 vs 23
set 82/100: game points 15 vs 19
set 83/100: game points 22 vs 22
set 84/100: game points 19 vs 21
set 85/100: game points 19 vs 18
set 86/100: game points 18 vs 19
set 87/100: game points 17 vs 17
set 88/100: game points 21 vs 22
set 89/100: game points 22 vs 19
set 90/100: game points 17 vs 19
set 91/100: game points 18 vs 16
set 92/100: game points 19 vs 15
set 93/100: game points 23 vs 22
set 94/100: game points 22 vs 19
set 95/100: game points 15 vs 17
set 96/100: game points 19 vs 20
set 97/100: game points 19 vs 20
set 98/100: game points 20 vs 17
set 99/100: game points 20 vs 18
set 100/100: game points 18 vs 18

100 sets, 5-seat with house:call, house:random, house:allin
sets won: bots/gen1/bot_a 47, bots/gen1/bot_b 40, tied 13
game points per set, bots/gen1/bot_a minus bots/gen1/bot_b: +0.56 (standard error 0.28)
chips: bots/gen1/bot_a +888904, bots/gen1/bot_b +747930

After 100+ sets Astra won for the first time against Opus which stumbled the resutls slightly. What was discovered were it was able to take advatnage of the weaker bots to such a good standard that after 100+ sets it actually took the victory. SO I ninstead decided to run the h2h model against some of the stronger models instead of a baseline to determine one unoquivical winner. 

After more tests, It has led me to believe that the winner is actually a draw. So going forward I will take the short term champion Claude for now as the champion of round one as it showed it can perform against Astra better but let Astra see the other models too. 

