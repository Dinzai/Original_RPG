import libviper

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

    def on_start(self):       
        self.owner.set_origin(self.owner.get_image_size().x() / 2, self.owner.get_image_size().y() / 2)
        self.owner.set_scale(3, 3)
        self.owner.set_position(-204, -30)
        self.game.remove_collision(self.owner)
        self.maxY = self.owner.get_position().y()
        self.timer = 0
        self.health = globals.player_current_health


    def on_update(self, delta):
        self.owner.play_anim(0, 2)
        self.timer += delta
        if self.timer >= 0 and self.timer < 3:
            self.maxY += 10 * delta
            self.owner.set_position(self.owner.get_position().x(), self.maxY)         
        elif self.timer > 3 and self.timer < 6:
            self.maxY -= 10 * delta
            self.owner.set_position(self.owner.get_position().x(), self.maxY)
        elif self.timer >= 6:
            self.timer = 0

    def on_click(self):
        pass

    def on_action(self):
        pass
