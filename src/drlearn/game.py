'''
The Game class represents the game logic, more importantly the state, the actions, and the state transition.
This class needs to be subclassed by the specific game.
'''

class Game:
    def __init__(self, alternate_turn=True, player_agnostic_state=True):
        self.alternate_turn = alternate_turn
        self.player_agnostic_state = player_agnostic_state
        
    def get_init_state(self):
        '''
        state:  (player_state, opponent_state, current_player, reward)
            player_state: a list containing the cards of the player
            opponent_state: a list containing the cards of the dealer
                only the first card of the dealer is displayed when playing against human 
            reward:  1    :  if current_player wins
                    -1    :  if the other player wins
                    0     :  game not finished
                    1e-4  :  game is tied
        when the player stands, it switches to the dealer. for convenience, the state becomes
                (opponent_state, player_state, current_player, reward)
        if the game has player agnostic state, the opponent_state is the same as the player state
        '''
        pass
    
    def to_neural_state(self, state):
        '''
        input state: (player_state, opponent_state, current_player, reward)
        output state: (player_neural_state, opponent_neural_state, current_player, reward)
            a neural state is a numpy array which can be fed to the neural network model
        if the game has player agnostic state, the opponent_state is the same as the player state
        '''
        pass

    def get_shape(self):
        pass

    def get_action_size(self):
        '''
        the number of actions.
        each action is denoted as 0 to N-1, where N is the number of actions 
        '''
        pass

    def get_next_state(self, state, player, action):
        '''
        this is the critical API which controls the state transition of the game.
        if player takes action on state, return the next state
        action must be a valid move
        '''
        pass

    def get_valid_actions(self, state, player):
        '''
        given the current state, return the valid vector of actions
        '''
        pass

    def get_player_agnostic_state(self, state, player):
        '''
        if the game does not have player agnostic state, just return the state back
        '''
        pass

    def get_symmetries(self, state, pi):
        '''
        if the game does not have symmetries as most board games, just return the state back
        '''
        pass

    def get_game_ended(self, state, player):
        '''
        this returns the ending status of the game:
            1   : if the player wins
            -1  : if the player loses
            0   : a tie
            1e-4: game not ended
        '''
        pass

    def state_to_string(self, state):
        '''
        this returns a string representation of the state, which needs to be unique, as it is used as the key to the dictionaries in MCTS
        '''
        pass

    @staticmethod
    def display(state):
        '''
        this shows the state for playing the game against a human player
        '''
        pass