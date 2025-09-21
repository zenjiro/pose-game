"""Audio management for the pose game using arcade library."""

from __future__ import annotations
import os
import arcade
from typing import Optional
import time


class AudioManager:
    """Manages game audio using arcade's sound system."""
    
    def __init__(self, sounds_dir: str = "sounds"):
        self.sounds_dir = sounds_dir
        self.sounds = {}
        self.last_hurry_alarm = 0.0
        self.hurry_alarm_interval = 2.0  # Play hurry alarm every 2 seconds
        self.enabled = True
        
        # Initialize arcade audio
        try:
            # Arcade handles audio initialization internally
            self._load_sounds()
        except Exception as e:
            print(f"Warning: Failed to initialize audio: {e}")
            self.enabled = False
    
    def _load_sounds(self) -> None:
        """Load all sound files from the sounds directory."""
        sound_files = {
            "game_start": "game_start.wav",
            "head_hit": "head_hit.wav", 
            "hand_hit": "hand_hit.wav",
            "foot_hit": "foot_hit.wav",
            "hurry_alarm": "hurry_alarm.wav",
            "game_over": "game_over.wav",
            "rock_drop": "rock_drop.wav"
        }
        
        for sound_name, filename in sound_files.items():
            filepath = os.path.join(self.sounds_dir, filename)
            if os.path.exists(filepath):
                try:
                    self.sounds[sound_name] = arcade.load_sound(filepath)
                    print(f"Loaded sound: {sound_name}")
                except Exception as e:
                    print(f"Warning: Failed to load {filepath}: {e}")
            else:
                print(f"Warning: Sound file not found: {filepath}")
    
    def play_sound(self, sound_name: str, volume: float = 1.0) -> None:
        """Play a sound by name."""
        if not self.enabled or sound_name not in self.sounds:
            return
        
        try:
            arcade.play_sound(self.sounds[sound_name], volume)
        except Exception as e:
            print(f"Warning: Failed to play sound {sound_name}: {e}")
    
    def play_game_start(self) -> None:
        """Play sound when starting a new game."""
        self.play_sound("game_start", volume=0.8)
    
    def play_head_hit(self) -> None:
        """Play sound when rock hits head (bad event)."""
        self.play_sound("head_hit", volume=0.9)
    
    def play_hand_hit(self) -> None:
        """Play sound when rock hits hands (somewhat good)."""
        self.play_sound("hand_hit", volume=0.7)
    
    def play_foot_hit(self) -> None:
        """Play sound when rock hits feet (very good)."""
        self.play_sound("foot_hit", volume=0.8)
    
    def play_hurry_alarm(self) -> None:
        """Play hurry alarm when time is running low (throttled)."""
        current_time = time.time()
        if current_time - self.last_hurry_alarm >= self.hurry_alarm_interval:
            self.play_sound("hurry_alarm", volume=0.6)  # Normal volume
            self.last_hurry_alarm = current_time
    
    def play_game_over(self) -> None:
        """Play sound when game finishes."""
        self.play_sound("game_over", volume=0.9)
    
    def play_rock_drop(self) -> None:
        """Play sound when a new rock is spawned/dropped."""
        self.play_sound("rock_drop", volume=0.4)  # Subtle volume since it happens frequently
    
    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable audio playback."""
        self.enabled = enabled
    
    def is_enabled(self) -> bool:
        """Check if audio is enabled."""
        return self.enabled