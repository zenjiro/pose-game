from __future__ import annotations

from typing import Dict, List
from .entities import Rock

from .pose import Circle
import arcade
import math


def draw_circles_arcade(groups: Dict[str, List[Circle]], height: int, color_shift: int = 0, color: tuple[int, int, int] | None = None, thickness: float = 2.0, prof=None) -> None:
    """Arcade version: draw head/hands/feet circles as outlines.
    Flip Y because Arcade's origin is bottom-left but our coordinates are top-left.
    """
    base_colors = {
        "head": (0, 200, 255),
        "hands": (60, 220, 60),
        "feet": (255, 80, 80),
    }
    for key, circles in groups.items():
        if color is not None:
            use_color = color
        else:
            base = base_colors.get(key, (255, 255, 255))
            use_color = tuple(int((c + color_shift) % 256) for c in base)
        # BGR -> RGB for Arcade
        col = (use_color[2], use_color[1], use_color[0])
        for c in circles:
            x = float(c.x)
            y = float(height - c.y)
            r = float(c.r)
            arcade.draw_circle_outline(x, y, r, col, border_width=thickness)


class RockSprite(arcade.Sprite):
    """Sprite representation of a rock for batch rendering."""
    
    def __init__(self, rock: Rock, screen_height: int):
        super().__init__()
        self.rock = rock
        self.screen_height = screen_height
        
        # Create a circular texture for the rock
        size = max(int(rock.r * 2) + 8, 16)  # Ensure minimum size of 16 pixels
        self.texture = self._create_rock_texture(size, rock.color, rock.r)
        
        # Set sprite properties
        self.center_x = rock.x
        self.center_y = screen_height - rock.y  # Flip Y coordinate
        
    def _create_rock_texture(self, size: int, color: tuple[int, int, int], radius: float) -> arcade.Texture:
        """Create a circular texture for the rock."""
        # Use PIL to create the texture
        import PIL.Image
        import PIL.ImageDraw
        
        # Create image with RGBA mode
        img = PIL.Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = PIL.ImageDraw.Draw(img)
        
        # Draw main circle
        center = size // 2
        left = center - radius
        top = center - radius
        right = center + radius
        bottom = center + radius
        draw.ellipse([left, top, right, bottom], fill=color)
        
        # Draw highlight
        highlight_radius = radius * 0.3
        hl_left = center - radius * 0.3 - highlight_radius
        hl_top = center + radius * 0.3 - highlight_radius  
        hl_right = center - radius * 0.3 + highlight_radius
        hl_bottom = center + radius * 0.3 + highlight_radius
        draw.ellipse([hl_left, hl_top, hl_right, hl_bottom], fill=(100, 100, 100))
        
        # Create arcade texture from PIL image - Arcade 3.3.2 takes PIL image directly
        texture = arcade.Texture(img)
        return texture
    
    def update_from_rock(self, rock: Rock):
        """Update sprite position from rock data."""
        self.rock = rock
        self.center_x = rock.x
        self.center_y = self.screen_height - rock.y
        
        # Handle hit effect
        if getattr(rock, "hit", False):
            # Could add scaling or color modification for hit effect
            pass


class RockSpriteList:
    """Manages a SpriteList for efficient rock rendering."""
    
    def __init__(self, screen_height: int):
        self.screen_height = screen_height
        self.sprite_list = arcade.SpriteList()
        self.rock_sprites: Dict[int, RockSprite] = {}  # rock id -> sprite mapping
        
    def update_rocks(self, rocks: List[Rock]):
        """Update the sprite list to match the current rocks."""
        # Get current rock IDs
        current_rock_ids = {id(rock) for rock in rocks}
        existing_sprite_ids = set(self.rock_sprites.keys())
        
        # Remove sprites for rocks that no longer exist
        to_remove = existing_sprite_ids - current_rock_ids
        for rock_id in to_remove:
            sprite = self.rock_sprites.pop(rock_id)
            sprite.remove_from_sprite_lists()
            
        # Add or update sprites for current rocks
        for rock in rocks:
            rock_id = id(rock)
            if rock_id in self.rock_sprites:
                # Update existing sprite
                self.rock_sprites[rock_id].update_from_rock(rock)
            else:
                # Create new sprite and add to sprite list
                sprite = RockSprite(rock, self.screen_height)
                self.rock_sprites[rock_id] = sprite
                self.sprite_list.append(sprite)
                
        # Only print debug info occasionally
        # if len(rocks) > 0 and len(rocks) % 5 == 0:  # Print every 5th rock count change
        #     print(f"[DEBUG] RockSpriteList: {len(rocks)} rocks, {len(self.sprite_list)} sprites")
    
    def draw(self):
        """Draw all rock sprites efficiently."""
        self.sprite_list.draw()
        
        # Draw hit effects separately (could be optimized further)
        for sprite in self.sprite_list:
            if getattr(sprite.rock, "hit", False):
                arcade.draw_circle_outline(
                    sprite.center_x, sprite.center_y, 
                    sprite.rock.r + 4, (200, 0, 0), border_width=3
                )


# Geometry-based circle drawing for pose circles
class CircleGeometry:
    """Optimized circle rendering using Arcade geometry."""
    
    def __init__(self):
        self.circle_cache = {}  # Cache for circle geometries by radius
        
    def _get_circle_geometry(self, radius: float, segments: int = 16):
        """Get or create a circle geometry for the given radius."""
        key = (radius, segments)
        if key not in self.circle_cache:
            # Create circle vertices
            vertices = []
            for i in range(segments):
                angle = 2 * math.pi * i / segments
                x = radius * math.cos(angle)
                y = radius * math.sin(angle)
                vertices.extend([x, y])
            
            # Create geometry (this is a simplified approach)
            # In a full implementation, we'd use proper OpenGL buffers
            self.circle_cache[key] = vertices
            
        return self.circle_cache[key]
    
    def draw_circles_batch(self, circles: List[tuple[float, float, float, tuple[int, int, int]]], height: int):
        """Draw multiple circles efficiently using geometry instancing."""
        # Group circles by radius for batching
        radius_groups = {}
        for x, y, r, color in circles:
            if r not in radius_groups:
                radius_groups[r] = []
            radius_groups[r].append((x, height - y, color))
        
        # Draw each radius group
        for radius, circle_data in radius_groups.items():
            for x, y, color in circle_data:
                # For now, fall back to individual draws
                # A full implementation would use instanced rendering
                arcade.draw_circle_outline(x, y, radius, color, border_width=2.0)


def draw_circles_arcade_optimized(groups: Dict[str, List[Circle]], height: int, 
                                color_shift: int = 0, color: tuple[int, int, int] | None = None, 
                                thickness: float = 2.0, geometry_renderer=None) -> None:
    """Optimized version using geometry rendering when available."""
    if geometry_renderer is None:
        # Fall back to original implementation
        return draw_circles_arcade(groups, height, color_shift, color, thickness)
    
    base_colors = {
        "head": (0, 200, 255),
        "hands": (60, 220, 60),
        "feet": (255, 80, 80),
    }
    
    # Collect all circles for batch rendering
    all_circles = []
    for key, circles in groups.items():
        if color is not None:
            use_color = color
        else:
            base = base_colors.get(key, (255, 255, 255))
            use_color = tuple(int((c + color_shift) % 256) for c in base)
        # BGR -> RGB for Arcade
        col = (use_color[2], use_color[1], use_color[0])
        
        for c in circles:
            all_circles.append((float(c.x), float(c.y), float(c.r), col))
    
    # Batch render all circles
    geometry_renderer.draw_circles_batch(all_circles, height)