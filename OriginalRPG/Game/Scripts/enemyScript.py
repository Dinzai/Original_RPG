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
        # type: (libviper.Generic, libviper.Loop) -> None
        self.owner = owner
        self.game = game
    
    def enemy_turn(self):
        pass

    def on_start(self):
        self.timer = 0
        self.owner.set_origin(self.owner.get_image_size().x() / 2, self.owner.get_image_size().y() / 2)
        self.owner.add_tag("ENEMY")
        self.owner.set_speed(25)
        self.owner.set_movement_frames(0,3,0,3,0,3,0,3)

    def on_update(self, delta):
        if self.game.collision_aabb_p_g(self.owner) and globals.enemy_intangible_after_run == False:
            globals.player_current_pos_x = self.game.get_player().get_position().x()
            globals.player_current_pos_y = self.game.get_player().get_position().y()
            self.game.load_scene("BATTLE")
        if globals.enemy_intangible_after_run == True:
            self.timer += delta
            if self.timer > 2:
                globals.enemy_intangible_after_run = False
                self.timer = 0
                
            

    def on_click(self):
        pass

    def on_action(self):
        pass
