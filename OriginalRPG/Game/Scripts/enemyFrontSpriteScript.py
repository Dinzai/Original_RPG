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
        self.owner.set_position(251, -171)
        self.y = self.owner.get_position().y()
        self.game.remove_collision(self.owner)

    def on_update(self, delta):
        self.owner.play_anim(0, 3)
        if globals.enemy_current_health <= 0:
            self.owner.play_anim(0, 0)
            self.y += 2000 * delta
            self.owner.set_position(self.owner.get_position().x(), self.y)

    def on_click(self):
        pass

    def on_action(self):
        pass
