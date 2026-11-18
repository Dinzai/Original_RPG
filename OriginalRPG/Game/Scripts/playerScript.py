import libviper

import math

import sys
from pathlib import Path

script_dir = str(Path(__file__).resolve().parent)
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

import globals

class Behaviour:
    def __init__(self, owner, game):
        # type: (libviper.Player, libviper.Loop) -> None
        self.owner = owner
        self.game = game
    
    def players_turn(self):
        pass

    def on_start(self):
        self.owner.set_origin(self.owner.get_image_size().x() / 2, self.owner.get_image_size().y() / 2)
        self.game.set_camera_zoom(0.45)
        
        self.owner.set_movement_frames(0,3,0,3,0,3,0,3)

    def on_update(self, delta):
        pass

    def on_click(self):
        pass

    def on_action(self):
        pass
