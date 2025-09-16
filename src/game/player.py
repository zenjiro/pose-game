"""Player state management for the pose game."""

from __future__ import annotations
from dataclasses import dataclass
import time


@dataclass
class PlayerState:
    """Represents the state of a single player."""
    player_id: int
    score: int = 0
    lives: int = 5
    last_hit_time: float = 0.0
    invulnerable_duration: float = 1.0  # seconds of invulnerability after head hit
    is_game_over: bool = False
    next_life_threshold: int = 3  # score at which the next bonus life is awarded

    def take_damage(self) -> bool:
        """Take damage (lose a life). Returns True if damage was taken, False if invulnerable."""
        current_time = time.time()
        
        # Check if still invulnerable from previous hit
        if current_time - self.last_hit_time < self.invulnerable_duration:
            return False
        
        self.lives -= 1
        self.last_hit_time = current_time
        
        if self.lives <= 0:
            self.is_game_over = True
        
        return True

    def add_score(self, points: int = 1) -> None:
        """Add points to score and award a life at thresholds (10, 20, 30, ...)."""
        if self.is_game_over:
            return
        self.score += points
        # Award one life per threshold crossed; supports points > 1
        while self.score >= self.next_life_threshold:
            self.lives += 1
            self.next_life_threshold += 3

    def is_invulnerable(self) -> bool:
        """Check if player is currently invulnerable to head hits."""
        current_time = time.time()
        return (current_time - self.last_hit_time) < self.invulnerable_duration

    def reset(self) -> None:
        """Reset player state for a new game."""
        self.score = 0
        self.lives = 5
        self.last_hit_time = 0.0
        self.is_game_over = False
        self.next_life_threshold = 3


class GameState:
    """Manages the overall game state and both players."""
    
    def __init__(self, num_players: int = 2, time_limit: int = 60):
        self.players = [PlayerState(i) for i in range(num_players)]
        self.game_over = False
        self.game_started = False  # Track if game has been started
        self.time_limit = time_limit
        self.start_time = 0.0
        self.game_over_time = 0.0

    def get_player(self, player_id: int) -> PlayerState:
        """Get player state by ID."""
        if 0 <= player_id < len(self.players):
            return self.players[player_id]
        raise IndexError(f"Player ID {player_id} out of range")

    def handle_head_hit(self, player_id: int) -> bool:
        """Handle a head hit for the specified player. Returns True if damage was taken."""
        if self.game_over:
            return False
        
        player = self.get_player(player_id)
        damage_taken = player.take_damage()
        
        # Check if game should end
        if any(p.is_game_over for p in self.players):
            self.set_game_over()
        
        return damage_taken

    def handle_foot_hit(self, player_id: int, points: int = 1) -> None:
        """Handle a foot hit (scoring) for the specified player."""
        if self.game_over:
            return
        
        player = self.get_player(player_id)
        player.add_score(points)

    def start_game(self) -> None:
        """Start the game from title screen."""
        self.game_started = True
        self.game_over = False
        self.start_time = time.time()
        self.game_over_time = self.time_limit
        for player in self.players:
            player.reset()

    def reset(self) -> None:
        """Reset the entire game state for restart."""
        for player in self.players:
            player.reset()
        self.game_over = False
        self.game_started = True  # Keep game started when restarting
        self.start_time = time.time()
        self.game_over_time = self.time_limit

    def get_winner(self) -> int | None:
        """Get the winning player ID, or None if tie/no winner yet."""
        if not self.game_over:
            return None
        
        # If one player is game over and other isn't, other wins
        active_players = [p for p in self.players if not p.is_game_over]
        if len(active_players) == 1:
            return active_players[0].player_id
        
        # If both are game over or time is up, highest score wins
        max_score = max(p.score for p in self.players)
        winners = [p for p in self.players if p.score == max_score]
        if len(winners) == 1:
            return winners[0].player_id
        
        return None  # Tie

    def set_game_over(self):
        if not self.game_over:
            self.game_over = True
            elapsed_time = time.time() - self.start_time
            self.game_over_time = max(0, self.time_limit - elapsed_time)

    def get_remaining_time(self) -> float:
        if not self.game_started:
            return self.time_limit
        if self.game_over:
            return self.game_over_time
        elapsed_time = time.time() - self.start_time
        return max(0, self.time_limit - elapsed_time)

    def update(self):
        if self.game_started and not self.game_over:
            if self.get_remaining_time() <= 0:
                self.set_game_over()