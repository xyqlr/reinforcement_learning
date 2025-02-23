import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import random
import copy
import logging
import argparse
import time
import os
import math
import sys
from tqdm import tqdm
from random import shuffle
from collections import deque
from pickle import Pickler, Unpickler

from rlearn.game import Game
from rlearn.utils import AverageMeter, dotdict
from rlearn.mcts import MCTS, EPS
from rlearn.arena import Arena
from rlearn.nnet import NeuralNetModel
from rlearn.agent import Agent
from rlearn.args import args, nnargs, parse_args, main

ACTION_HIT   = 0
ACTION_STAND = 1
PLAYER = 1
DEALER = -1

# Custom Blackjack Environment
class BlackJack(Game):
    def __init__(self):
        super().__init__(alternate_turn=False, player_agnostic_state=False)
        self.n = 13
        self.reset()

    def reset(self):
        # Reset the deck
        self.suite = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
        self.deck = self.suite * 4  # Deck of cards
        random.shuffle(self.deck)
        
        # Reset player and dealer hands
        self.current_player = 1 #player, -1 for dealer
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]
        self.index_map = {k:i for i,k in enumerate(self.suite)}
        # Card values: Ace=1, 2=2, ..., 10=10, Jack=10, Queen=10, King=10
        self.card_values = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10])

    def get_init_state(self):
        '''
        state:  (player_state, dealer_state, current_player, reward)
            player_state: a list containing the cards of the player
            dealer_state: a list containing the cards of the dealer
                only the first card of the dealer is displayed when playing against human 
            reward:  1    :  if current_player wins
                    -1    :  if the other player wins
                    0     :  game not finished
                    1e-4  :  game is tied
        when the player stands, it switches to the dealer. for convenicne, the state becomes
                (dealer_state, player_state, current_player, reward)
        '''
        self.reset()
        return self.player_hand, self.dealer_hand, self.current_player, 0
    
    def to_neural_state(self, state):
        '''
        input state: (player_state, dealer_state, current_player, reward)
        output state: (player_neural_state, dealer_neural_state, current_player, reward)
            a neural state is a numpy array of dimension 14, 
                the first 13 store the count of each card in a hand
                the last element is different fro the player and the dealer
                    it is the first card of the dealer for player_neural_state,
                    it is the the value of the cards of the player for dealer_neural_state.
            player_neural_state: [num As, num 2s, ..., num Ks, the first card of the dealer]
            dealer_neural_state: [num As, num 2s, ..., num Ks, the total value of the player]
        '''
        current_player = state[2]
        player, dealer = 0, 1
        if current_player == -1:
            player, dealer = 1, 0
        player_state = np.zeros(self.n+1, dtype=int)
        for card in state[player]:
            player_state[self.index_map[card]] += 1  
        player_state[self.n] = self.card_values[self.index_map[state[dealer][0]]] #the first card of the dealer
        dealer_state = np.zeros(self.n+1, dtype=int)
        for card in state[dealer]:
            dealer_state[self.index_map[card]] += 1  
        dealer_state[self.n] = max(self._get_value(player_state))
        return (player_state, dealer_state, state[2], state[3]) if current_player == 1 else (dealer_state, player_state, state[2], state[3])

    def get_shape(self):
        return (self.n, self.n)

    def get_action_size(self):
        '''
        the number of actions: 2
            ACTION_HIT  : hit for more cards
            ACTION_STAND: stand, no more cards for the player and dealer plays next
        '''
        return 2

    def get_next_state(self, state, player, action):
        '''
        this is the critical API which controls the state transition of the game.
        if player takes action on state, return the next state
        action must be a valid move
        '''
        state0 = copy.copy(state[0])
        state1 = copy.copy(state[1])
        if action == ACTION_HIT:  # Hit
            card = self._deal_next_card(state)
            state0.append(card)
            state_np, _, _, _ = self.to_neural_state((state0, state1, state[2], state[3]))
            if min(self._get_value(state_np)) > 21:
                #reward is from the current player's perspective
                reward = -player if player == 1 else player
                return state0, state1, state[2], reward     #no change of player at the end of the game
            else:
                return state0, state1, state[2], 0
        else:  # Stand
            if player == 1:
                return state1, state0, -1, 0    #dealer's turn
            dealer_state, player_state, _, _ = self.to_neural_state(state)
            dealer_sum = max(self._get_value(dealer_state))
            player_sum = max(self._get_value(player_state))
            #reward is from the current player's perspective
            if player_sum > dealer_sum:
                return state0, state1, state[2], -1
            elif player_sum == dealer_sum:
                return state0, state1, state[2], 1e-4 #small value for tie
            else:
                return state0, state1, state[2], 1

    def get_valid_actions(self, state, player):
        '''
        given the current state, return the valid vector of actions
        '''
        valids = [1]*self.get_action_size()
        current_player = state[2]
        if current_player == -1: #dealer
            dealer_state, player_state, _, _ = self.to_neural_state(state)
            dealer_value = self._get_value(dealer_state)
            if max(dealer_value) < 17:
                valids[1] = 0
            elif min(dealer_value) > 21:
                valids[0] = 0
                valids[1] = 0
        else:            
            player_state, dealer_state, _, _ = self.to_neural_state(state)
            player_value = self._get_value(player_state)
            if min(player_value) > 21:
                valids[0] = 0
                valids[1] = 0
        return np.array(valids)

    def get_player_agnostic_state(self, state, player):
        return state

    def get_symmetries(self, state, pi):
        return [state, pi]

    def get_game_ended(self, state, player):
        '''
        this returns the ending status of the game:
            1   : if the player wins
            -1  : if the player loses
            0   : a tie
            1e-4: game not ended
        '''
        return state[3]

    def state_to_string(self, state):
        current_player = state[2]
        if current_player == 1:
            dealer_str = str(self.card_values[self.index_map[state[1][0]]])    #the first card of the dealer
            player_state, _, _, _ = self.to_neural_state(state)
            return ''.join([str(v) for k,v in enumerate(player_state[:-1])])+":"+dealer_str+":"+str(current_player) #add current_play to avoid same state when switching to dealer
        else:
            dealer_state, player_state, _, _ = self.to_neural_state(state)
            dealer_value = max(self._get_value(dealer_state))
            return ''.join([str(v) for k,v in enumerate(player_state[:-1])])+":"+str(dealer_value)+":"+str(current_player)

    @staticmethod
    def display(state):
        player_state, dealer_state, current_player, _ = state
        if current_player == -1:
            dealer_state, player_state, _, _ = state
            dealer_str = ','.join(x for x in dealer_state)
        else:
            dealer_str = dealer_state[0]
        print(f"dealer: {dealer_str}")
        player_str = ','.join(x for x in player_state)
        print(f"player: {player_str}\n")

    def _deal_next_card(self, state):
        """
        Perform weighted sampling from a dictionary.

        Args:
            state: A tuple with player's and dealer's cards.

        Returns:
            str: a card.
        """

        # get the remainng cards
        cards = {k:4 for k in self.suite}
        for hand in range(2):
            for card in state[hand]:
                cards[card] -= 1

        # Extract keys and weights
        keys = list(cards.keys())
        weights = list(cards.values())

        # Normalize weights to probabilities
        total_weight = sum(weights)
        probabilities = [w / total_weight for w in weights]

        # Perform weighted sampling
        card = random.choices(keys, weights=probabilities, k=1)
        return card[0]
        
    def _get_value(self, state):
        """
        Compute all possible values of a Blackjack hand using a NumPy array of card counts.
        
        Args:
            state (np.array): Array of card counts, where:
                                    - card_counts[0] = number of Aces
                                    - card_counts[1] = number of 2s
                                    - ...
                                    - card_counts[12] = number of Kings
        
        Returns:
            set: A set of possible hand values.
        """
        
        # Base value: treat all Aces as 1
        base_value = np.sum(state[:-1] * self.card_values) #exclude the last one
        
        # Number of Aces
        num_aces = state[0]
        
        if num_aces ==0 or base_value > 21:
            return [base_value]
        # Possible values: add 10 for each Ace that can be treated as 11
        possible_values = [base_value + 10 * i for i in range(num_aces + 1) if base_value + 10 * i <= 21]
        
        return possible_values
    
class HumanBlackJackPlayer():
    def __init__(self, game):
        self.game = game

    def play(self, state):
        # display(state)
        valid = self.game.get_valid_actions(state, 1)
        str = f"Enter 0 for hit\n" if valid[0] else f""
        str += f"Enter 1 for stand" if valid[1] else f""
        print(str)
        while True: 
            a = input()
            a = int(a)
            if valid[a]:
                break
            else:
                print('Invalid')

        return a

class BlackJackModel(NeuralNetModel):
    def __init__(self, game, args):
        # game params
        self.state_size = game.get_shape()[0]+1
        self.action_size = game.get_action_size()
        super().__init__(game, args, (self.state_size, ))
        self.fc1 = nn.Linear(self.state_size, args.num_channels)
        self.fc2 = nn.Linear(args.num_channels, args.num_channels)
        self.fc3 = nn.Linear(args.num_channels, self.action_size)
        self.fc4 = nn.Linear(args.num_channels, 1)

    def forward(self, x):
        x = torch.relu(self.fc1(x))
        x = torch.relu(self.fc2(x))
        pi = self.fc3(x)    
        v = self.fc4(x)  

        return F.log_softmax(pi, dim=1), torch.tanh(v)

class BlackJackAgent(Agent):
    """
    This class executes the self-play + learning. It uses the functions defined
    in Game and NeuralNet. args are specified in main.py.
    https://github.com/suragnair/alpha-zero-general
    """

    def __init__(self, game, nnet, dealnet_net, mcts, args, nnargs=None):
        self.game = game
        self.nnet = nnet
        self.pnet = self.nnet.__class__(self.game, nnargs)  # the competitor network
        self.dealer_nnet = dealer_nnet  # the dealer network
        self.dealer_pnet = self.nnet.__class__(self.game, nnargs)  # the previous dealer network
        self.args = args
        self.mcts = mcts
        self.trainExamplesHistory = []  # history of examples from args.numItersForTrainExamplesHistory latest iterations
        self.skipFirstSelfPlay = False  # can be overriden in load_train_examples()

    def execute_episode(self):
        """
        This function executes one episode of self-play, starting with player 1.
        As the game is played, each turn is added as a training example to
        trainExamples. The game is played till the game ends. After the game
        ends, the outcome of the game is used to assign values to each example
        in trainExamples.

        It uses a temp=1 if episodeStep < tempThreshold, and thereafter
        uses temp=0.

        Returns:
            trainExamples: a list of examples of the form (state, currPlayer, pi,v)
                           pi is the MCTS informed policy vector, v is +1 if
                           the player eventually won the game, else -1.
        """
        trainExamples = []
        state = self.game.get_init_state()
        current_player = state[2]
        step = 0

        while True:
            step += 1
            temp = int(step < self.args.tempThreshold)

            pi = self.mcts.get_action_prob(state, temp=temp)
            state0, state1, _, _ = self.game.to_neural_state(state)
            trainExamples.append([state0, current_player, pi])

            action = np.random.choice(len(pi), p=pi)
            state= self.game.get_next_state(state, current_player, action)
            current_player = state[2]
            r = state[3]

            if r != 0:
                return [(x[0], x[2], x[1], x[1]) for x in trainExamples]

    def learn(self):
        """
        Performs numIters iterations with numEps episodes of self-play in each
        iteration. After every iteration, it retrains neural network with
        examples in trainExamples (which has a maximum length of maxlenofQueue).
        It then pits the new neural network against the old one and accepts it
        only if it wins >= updateThreshold fraction of games.
        """

        for i in range(1, self.args.numIters + 1):
            # bookkeeping
            logging.info(f'Starting Iter #{i} ...')
            # examples of the iteration
            if not self.skipFirstSelfPlay or i > 1:
                iterationTrainExamples = deque([], maxlen=self.args.maxlenOfQueue)

                for j in tqdm(range(self.args.numEps), desc="Self Play"):
                    self.mcts = MCTS(self.game, self.nnet, self.dealer_nnet, self.args)  # reset search tree
                    iterationTrainExamples += self.execute_episode()

                # save the iteration examples to the history 
                self.trainExamplesHistory.append(iterationTrainExamples)

            if len(self.trainExamplesHistory) > self.args.numItersForTrainExamplesHistory:
                logging.warning(
                    f"Removing the oldest entry in trainExamples. len(trainExamplesHistory) = {len(self.trainExamplesHistory)}")
                self.trainExamplesHistory.pop(0)
            # backup history to a file
            # NB! the examples were collected using the model from the previous iteration, so (i-1)  
            #self.save_train_examples(i - 1)

            # shuffle examples before training
            trainExamples = []
            for e in self.trainExamplesHistory:
                trainExamples.extend(e)
            shuffle(trainExamples)

            # training new network, keeping a copy of the old one
            self.nnet.save_checkpoint(folder=self.args.checkpoint, filename='temp.tar')
            self.pnet.load_checkpoint(folder=self.args.checkpoint, filename='temp.tar')
            self.dealer_nnet.save_checkpoint(folder=self.args.checkpoint, filename='tempd.tar')
            self.dealer_pnet.load_checkpoint(folder=self.args.checkpoint, filename='tempd.tar')
            pmcts = MCTS(self.game, self.pnet, self.dealer_pnet, self.args)

            player_examples = [(x[0],x[1],x[2]) for x in trainExamples if x[3]==1]
            dealer_examples = [(x[0],x[1],x[2]) for x in trainExamples if x[3]==-1]
            self.nnet.fit(player_examples)
            self.dealer_nnet.fit(dealer_examples)

            nmcts = MCTS(self.game, self.nnet, self.dealer_nnet, self.args)

            logging.info('PLAYING AGAINST PREVIOUS VERSION')
            arena = Arena(lambda x: np.argmax(nmcts.get_action_prob(x, temp=0)),
                          lambda x: np.argmax(pmcts.get_action_prob(x, temp=0)), self.game)
            nwins, pwins, draws = arena.eval_games(self.args.games_eval)

            #save the first iteration models as the base
            if i==1:
                self.nnet.save_checkpoint(folder=self.args.checkpoint, filename='best.tar')
                self.dealer_nnet.save_checkpoint(folder=self.args.checkpoint, filename='bestd.tar')
                self.save_train_examples(i-1, best=True)


            logging.info('NEW/PREV WINS : %d / %d ; DRAWS : %d' % (nwins, pwins, draws))
            if pwins + nwins == 0 or float(nwins) / (pwins + nwins) < self.args.updateThreshold:
                logging.info('REJECTING NEW MODEL')
                self.nnet.load_checkpoint(folder=self.args.checkpoint, filename='temp.tar')
                self.dealer_nnet.load_checkpoint(folder=self.args.checkpoint, filename='tempd.tar')
            else:
                logging.info('ACCEPTING NEW MODEL')
                self.nnet.save_checkpoint(folder=self.args.checkpoint, filename='best.tar')
                self.dealer_nnet.save_checkpoint(folder=self.args.checkpoint, filename='bestd.tar')
                self.save_train_examples(i - 1, best=True)

if __name__ == "__main__":
    nnargs.channels = 512     #set the default
    args.numMCTSSims=50
    args.numEps=100
    parse_args()
    game = BlackJack()
    nnet = BlackJackModel(game, nnargs)
    dealer_nnet = BlackJackModel(game, nnargs)
    mcts = MCTS(game, nnet, dealer_nnet, args)
    agent = None
    if args.eval or args.play or args.load_model:
        dealer_nnet.load_checkpoint(folder=args.checkpoint, filename='bestd.tar')
    else:
        agent = BlackJackAgent(game, nnet, dealer_nnet, mcts, args, nnargs)
    human_player = HumanBlackJackPlayer(game)
    main(game, nnet, mcts, human_player, agent)